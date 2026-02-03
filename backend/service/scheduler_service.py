"""
Workflow Scheduler Service

Provides scheduling capabilities for automated workflow execution.
Supports one-time, interval, cron-style, and recurring schedules.
"""
import asyncio
import json
import os
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Try to import APScheduler
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.jobstores.memory import MemoryJobStore
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed. Run: pip install apscheduler")


class ScheduleType(str, Enum):
    """Types of schedules supported."""
    ONCE = "once"           # Run once at a specific time
    INTERVAL = "interval"   # Run every X minutes/hours/days
    DAILY = "daily"         # Run daily at a specific time
    WEEKLY = "weekly"       # Run weekly on specific days
    MONTHLY = "monthly"     # Run monthly on specific day
    CRON = "cron"           # Custom cron expression


@dataclass
class ScheduledWorkflow:
    """Represents a scheduled workflow job."""
    id: str
    workflow_id: str
    workflow_name: str
    session_id: str
    schedule_type: ScheduleType
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0
    
    # Execution status tracking
    last_status: Optional[str] = None     # "success", "failed", "running", None
    last_error: Optional[str] = None      # Error message if last run failed
    success_count: int = 0
    failure_count: int = 0
    
    # Schedule parameters
    run_at: Optional[str] = None          # For ONCE: ISO datetime
    interval_minutes: Optional[int] = None # For INTERVAL
    time_of_day: Optional[str] = None     # For DAILY/WEEKLY/MONTHLY: "HH:MM"
    days_of_week: Optional[List[int]] = None  # For WEEKLY: 0=Mon, 6=Sun
    day_of_month: Optional[int] = None    # For MONTHLY: 1-31
    cron_expression: Optional[str] = None # For CRON
    timezone: str = "UTC"
    
    # Execution settings
    timeout: int = 300
    retry_on_failure: bool = False
    max_retries: int = 3
    max_runs: Optional[int] = None  # Maximum number of times to run (None = unlimited)
    
    # Metadata
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    workflow_goal: Optional[str] = None  # Goal from workflow designer
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['schedule_type'] = self.schedule_type.value if isinstance(self.schedule_type, ScheduleType) else self.schedule_type
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScheduledWorkflow':
        """Create from dictionary."""
        if isinstance(data.get('schedule_type'), str):
            data['schedule_type'] = ScheduleType(data['schedule_type'])
        
        # Handle backward compatibility for new fields
        data.setdefault('last_status', None)
        data.setdefault('last_error', None)
        data.setdefault('success_count', 0)
        data.setdefault('failure_count', 0)
        data.setdefault('workflow_goal', None)
        
        return cls(**data)


class WorkflowScheduler:
    """
    Manages scheduled workflow executions.
    
    Uses APScheduler for reliable job scheduling with persistence.
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.schedules_file = self.data_dir / "scheduled_workflows.json"
        self.run_history_file = self.data_dir / "schedule_run_history.json"
        self.schedules: Dict[str, ScheduledWorkflow] = {}
        self.run_history: List[Dict[str, Any]] = []
        self.scheduler: Optional[Any] = None
        self._workflow_executor: Optional[Callable] = None
        self._is_running = False
        self._main_event_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Try to connect to database
        self.database_url = os.environ.get('DATABASE_URL')
        self.use_database = False
        self.db_conn = None
        
        if self.database_url:
            try:
                self.db_conn = psycopg2.connect(self.database_url)
                self.use_database = True
                logger.info("[WorkflowScheduler] ✅ Using PostgreSQL database")
            except Exception as e:
                logger.warning(f"[WorkflowScheduler] ⚠️  Database connection failed: {e}")
                logger.warning("[WorkflowScheduler] Falling back to JSON file storage")
        
        if not self.use_database:
            # Ensure data directory exists for JSON fallback
            self.data_dir.mkdir(parents=True, exist_ok=True)
            logger.info("[WorkflowScheduler] Using JSON file storage")
        
        # Load existing schedules and history
        self._load_schedules()
        self._load_run_history()
    
    def _load_schedules(self):
        """Load schedules from database or persistent storage."""
        if self.use_database:
            self._load_schedules_from_database()
        else:
            self._load_schedules_from_file()
    
    def _load_schedules_from_database(self):
        """Load schedules from PostgreSQL database."""
        try:
            cur = self.db_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM scheduled_workflows
                ORDER BY created_at DESC
            """)
            
            for row in cur.fetchall():
                schedule_data = dict(row)
                # Convert datetime objects to ISO strings
                for key in ['created_at', 'updated_at', 'last_run', 'next_run', 'run_at']:
                    if schedule_data.get(key):
                        schedule_data[key] = schedule_data[key].isoformat()
                
                schedule = ScheduledWorkflow.from_dict(schedule_data)
                self.schedules[schedule.id] = schedule
            
            cur.close()
            logger.info(f"[WorkflowScheduler] Loaded {len(self.schedules)} scheduled workflows from database")
        except Exception as e:
            logger.error(f"[WorkflowScheduler] Error loading from database: {e}")
    
    def _load_schedules_from_file(self):
        """Load schedules from JSON file."""
        if self.schedules_file.exists():
            try:
                with open(self.schedules_file, 'r') as f:
                    data = json.load(f)
                    for item in data:
                        schedule = ScheduledWorkflow.from_dict(item)
                        self.schedules[schedule.id] = schedule
                logger.info(f"[WorkflowScheduler] Loaded {len(self.schedules)} scheduled workflows")
            except Exception as e:
                logger.error(f"[WorkflowScheduler] Error loading schedules: {e}")
                self.schedules = {}
    
    def _save_schedules(self):
        """Save schedules to database or persistent storage."""
        if self.use_database:
            # Database saves are done per-schedule in _save_schedule_to_database
            pass
        else:
            self._save_schedules_to_file()
    
    def _save_schedules_to_file(self):
        """Save schedules to JSON file."""
        try:
            data = [s.to_dict() for s in self.schedules.values()]
            with open(self.schedules_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"[WorkflowScheduler] Saved {len(self.schedules)} schedules to file")
        except Exception as e:
            logger.error(f"[WorkflowScheduler] Error saving schedules: {e}")
    
    def _save_schedule_to_database(self, schedule: ScheduledWorkflow) -> bool:
        """Save a single schedule to PostgreSQL database using UPSERT."""
        try:
            cur = self.db_conn.cursor()
            cur.execute("""
                INSERT INTO scheduled_workflows (
                    id, workflow_id, workflow_name, session_id, schedule_type,
                    enabled, created_at, updated_at, last_run, next_run, run_count,
                    last_status, last_error, success_count, failure_count,
                    run_at, interval_minutes, time_of_day, days_of_week, day_of_month,
                    cron_expression, timezone, timeout, retry_on_failure, max_retries, max_runs,
                    description, tags, workflow_goal
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    workflow_id = EXCLUDED.workflow_id,
                    workflow_name = EXCLUDED.workflow_name,
                    enabled = EXCLUDED.enabled,
                    updated_at = EXCLUDED.updated_at,
                    last_run = EXCLUDED.last_run,
                    next_run = EXCLUDED.next_run,
                    run_count = EXCLUDED.run_count,
                    last_status = EXCLUDED.last_status,
                    last_error = EXCLUDED.last_error,
                    success_count = EXCLUDED.success_count,
                    failure_count = EXCLUDED.failure_count,
                    interval_minutes = EXCLUDED.interval_minutes,
                    max_runs = EXCLUDED.max_runs
            """, (
                schedule.id,
                schedule.workflow_id,
                schedule.workflow_name,
                schedule.session_id,
                schedule.schedule_type.value if isinstance(schedule.schedule_type, ScheduleType) else schedule.schedule_type,
                schedule.enabled,
                schedule.created_at,
                schedule.updated_at,
                schedule.last_run,
                schedule.next_run,
                schedule.run_count,
                schedule.last_status,
                schedule.last_error,
                schedule.success_count,
                schedule.failure_count,
                schedule.run_at,
                schedule.interval_minutes,
                schedule.time_of_day,
                json.dumps(schedule.days_of_week) if schedule.days_of_week else None,
                schedule.day_of_month,
                schedule.cron_expression,
                schedule.timezone,
                schedule.timeout,
                schedule.retry_on_failure,
                schedule.max_retries,
                schedule.max_runs,
                schedule.description,
                json.dumps(schedule.tags),
                schedule.workflow_goal
            ))
            self.db_conn.commit()
            cur.close()
            return True
        except Exception as e:
            logger.error(f"[WorkflowScheduler] Error saving schedule to database: {e}")
            self.db_conn.rollback()
            return False
    
    def _delete_schedule_from_database(self, schedule_id: str) -> bool:
        """Delete a schedule from PostgreSQL database."""
        try:
            cur = self.db_conn.cursor()
            cur.execute("DELETE FROM scheduled_workflows WHERE id = %s", (schedule_id,))
            rows_deleted = cur.rowcount
            self.db_conn.commit()
            cur.close()
            return rows_deleted > 0
        except Exception as e:
            logger.error(f"[WorkflowScheduler] Error deleting schedule from database: {e}")
            self.db_conn.rollback()
            return False
    
    def _old_save_schedules(self):
        """Old save method - replaced by database methods."""
        try:
            data = [s.to_dict() for s in self.schedules.values()]
            with open(self.schedules_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving schedules: {e}")
    
    def _load_run_history(self):
        """Load run history from database or file."""
        if self.use_database:
            # When using database, we don't load all history into memory
            # History is queried on-demand via get_run_history()
            self.run_history = []
            logger.info("[WorkflowScheduler] Run history will be queried from database")
        else:
            # Fallback to JSON file
            if self.run_history_file.exists():
                try:
                    with open(self.run_history_file, 'r') as f:
                        self.run_history = json.load(f)
                    logger.info(f"Loaded {len(self.run_history)} run history entries from file")
                except Exception as e:
                    logger.error(f"Error loading run history: {e}")
                    self.run_history = []
            else:
                self.run_history = []
    
    def _save_run_history(self):
        """Save run history to file (JSON fallback only)."""
        try:
            # Keep only last 500 entries to avoid file growth
            with open(self.run_history_file, 'w') as f:
                json.dump(self.run_history[-500:], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving run history: {e}")
    
    def _add_run_history_to_database(self, run_id: str, schedule_id: str, workflow_id: str, 
                                      workflow_name: str, session_id: str, timestamp: str,
                                      started_at: str, completed_at: str, duration_seconds: float,
                                      status: str, result: Optional[str], error: Optional[str]):
        """Add run history entry to database."""
        if not self.db_conn:
            logger.error("No database connection available")
            return
        
        try:
            cur = self.db_conn.cursor()
            
            # Convert ISO strings to datetime objects
            timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            started_at_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            completed_at_dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
            
            cur.execute("""
                INSERT INTO schedule_run_history (
                    run_id, schedule_id, workflow_id, workflow_name, session_id,
                    timestamp, started_at, completed_at, duration_seconds,
                    status, result, error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                run_id, schedule_id, workflow_id, workflow_name, session_id,
                timestamp_dt, started_at_dt, completed_at_dt, duration_seconds,
                status, result, error
            ))
            
            self.db_conn.commit()
            cur.close()
            logger.debug(f"[WorkflowScheduler] Saved run history {run_id} to database")
        except Exception as e:
            logger.error(f"[WorkflowScheduler] Error saving run history to database: {e}")
            if self.db_conn:
                self.db_conn.rollback()
    
    def _add_run_history(self, schedule_id: str, workflow_id: str, workflow_name: str, session_id: str, 
                         status: str, result: Optional[str] = None, error: Optional[str] = None,
                         started_at: Optional[str] = None, completed_at: Optional[str] = None,
                         execution_time: Optional[float] = None):
        """Add a run history entry."""
        now = datetime.utcnow().isoformat()
        entry = {
            "run_id": str(uuid.uuid4()),
            "schedule_id": schedule_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "session_id": session_id,
            "timestamp": now,
            "started_at": started_at or now,
            "completed_at": completed_at or now,
            "duration_seconds": execution_time or 0,
            "status": status,
            "result": result[:5000] if result else None,  # Truncate to 5000 chars
            "error": error,
        }
        
        if self.use_database:
            self._add_run_history_to_database(
                run_id=entry["run_id"],
                schedule_id=entry["schedule_id"],
                workflow_id=entry["workflow_id"],
                workflow_name=entry["workflow_name"],
                session_id=entry["session_id"],
                timestamp=entry["timestamp"],
                started_at=entry["started_at"],
                completed_at=entry["completed_at"],
                duration_seconds=entry["duration_seconds"],
                status=entry["status"],
                result=entry["result"],
                error=entry["error"]
            )
        else:
            self.run_history.append(entry)
            self._save_run_history()
        
        return entry

    def set_workflow_executor(self, executor: Callable):
        """Set the function that executes workflows."""
        self._workflow_executor = executor
    
    async def start(self):
        """Start the scheduler."""
        if not APSCHEDULER_AVAILABLE:
            logger.error("APScheduler not available. Scheduler will not start.")
            return False
        
        if self._is_running:
            logger.warning("Scheduler is already running")
            return True
        
        try:
            # Get the current event loop and store reference for thread-safe calls
            loop = asyncio.get_event_loop()
            self._main_event_loop = loop
            print(f"[Scheduler] Starting scheduler with event loop: {loop}")
            
            self.scheduler = AsyncIOScheduler(
                jobstores={'default': MemoryJobStore()},
                timezone='UTC',
                event_loop=loop  # Explicitly pass the event loop
            )
            
            # Start the scheduler first
            self.scheduler.start()
            self._is_running = True
            print(f"[Scheduler] ✅ AsyncIOScheduler started, running={self.scheduler.running}")
            
            # Then restore all enabled schedules
            logger.info(f"🕐 Restoring {len([s for s in self.schedules.values() if s.enabled])} enabled schedules...")
            for schedule in self.schedules.values():
                if schedule.enabled:
                    self._add_job_to_scheduler(schedule)
            
            logger.info(f"🕐 Workflow scheduler started with {len(self.schedules)} total schedules")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def stop(self):
        """Stop the scheduler."""
        if self.scheduler and self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("🛑 Workflow scheduler stopped")
    
    def _add_job_to_scheduler(self, schedule: ScheduledWorkflow):
        """Add a job to the APScheduler."""
        print(f"[Scheduler] _add_job_to_scheduler called for {schedule.id}, scheduler={self.scheduler is not None}, _is_running={self._is_running}")
        
        if not self.scheduler or not self._is_running:
            print(f"[Scheduler] ❌ Cannot add job: scheduler={self.scheduler is not None}, _is_running={self._is_running}")
            return
        
        try:
            print(f"[Scheduler] Creating trigger for schedule type: {schedule.schedule_type}")
            trigger = self._create_trigger(schedule)
            if trigger:
                print(f"[Scheduler] Trigger created: {trigger}, adding job to scheduler...")
                self.scheduler.add_job(
                    self._execute_scheduled_workflow_sync,
                    trigger=trigger,
                    id=schedule.id,
                    args=[schedule.id],
                    replace_existing=True,
                    misfire_grace_time=60
                )
                
                # Update next run time
                job = self.scheduler.get_job(schedule.id)
                if job and job.next_run_time:
                    schedule.next_run = job.next_run_time.isoformat()
                    if self.use_database:
                        self._save_schedule_to_database(schedule)
                    else:
                        self._save_schedules()
                    print(f"[Scheduler] 📅 Job added! Next run: {job.next_run_time}")
                    
                print(f"[Scheduler] 📅 Scheduled workflow '{schedule.workflow_name}' ({schedule.schedule_type.value})")
            else:
                print(f"[Scheduler] ❌ Failed to create trigger for schedule {schedule.id}")
                
        except Exception as e:
            print(f"[Scheduler] ❌ Error adding job to scheduler: {e}")
            import traceback
            traceback.print_exc()
    
    def _create_trigger(self, schedule: ScheduledWorkflow):
        """Create an APScheduler trigger based on schedule type."""
        try:
            if schedule.schedule_type == ScheduleType.ONCE:
                if schedule.run_at:
                    run_time = datetime.fromisoformat(schedule.run_at.replace('Z', '+00:00'))
                    return DateTrigger(run_date=run_time)
                    
            elif schedule.schedule_type == ScheduleType.INTERVAL:
                if schedule.interval_minutes:
                    return IntervalTrigger(minutes=schedule.interval_minutes)
                    
            elif schedule.schedule_type == ScheduleType.DAILY:
                if schedule.time_of_day:
                    hour, minute = map(int, schedule.time_of_day.split(':'))
                    return CronTrigger(hour=hour, minute=minute)
                    
            elif schedule.schedule_type == ScheduleType.WEEKLY:
                if schedule.time_of_day and schedule.days_of_week:
                    hour, minute = map(int, schedule.time_of_day.split(':'))
                    # Convert to cron day_of_week format (0=Mon in our UI, but cron uses 0=Sun)
                    # APScheduler uses 0=Mon like us, so we're good
                    days = ','.join(str(d) for d in schedule.days_of_week)
                    return CronTrigger(hour=hour, minute=minute, day_of_week=days)
                    
            elif schedule.schedule_type == ScheduleType.MONTHLY:
                if schedule.time_of_day and schedule.day_of_month:
                    hour, minute = map(int, schedule.time_of_day.split(':'))
                    return CronTrigger(hour=hour, minute=minute, day=schedule.day_of_month)
                    
            elif schedule.schedule_type == ScheduleType.CRON:
                if schedule.cron_expression:
                    # Parse cron expression: "minute hour day month day_of_week"
                    parts = schedule.cron_expression.split()
                    if len(parts) >= 5:
                        return CronTrigger(
                            minute=parts[0],
                            hour=parts[1],
                            day=parts[2],
                            month=parts[3],
                            day_of_week=parts[4]
                        )
                        
        except Exception as e:
            logger.error(f"Error creating trigger for schedule {schedule.id}: {e}")
        
        return None
    
    def _execute_scheduled_workflow_sync(self, schedule_id: str):
        """Synchronous wrapper to execute a scheduled workflow."""
        print(f"[Scheduler] ⏰⏰⏰ TRIGGER! Scheduler triggered for workflow ID: {schedule_id}")
        logger.info(f"⏰ Scheduler triggered for workflow ID: {schedule_id}")
        
        # Run the async execution in the main event loop (thread-safe)
        try:
            if self._main_event_loop and self._main_event_loop.is_running():
                # Use run_coroutine_threadsafe to schedule on the main event loop
                print(f"[Scheduler] Scheduling workflow execution on main event loop...")
                future = asyncio.run_coroutine_threadsafe(
                    self._execute_scheduled_workflow(schedule_id),
                    self._main_event_loop
                )
                print(f"[Scheduler] ✅ Workflow execution scheduled on main event loop")
                # Don't wait for result - let it run asynchronously
            else:
                # Fallback: create a new event loop
                print(f"[Scheduler] No main event loop, using asyncio.run()...")
                asyncio.run(self._execute_scheduled_workflow(schedule_id))
                print(f"[Scheduler] Workflow execution complete")
        except Exception as e:
            print(f"[Scheduler] ❌ Error in scheduler wrapper: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"Error in scheduler wrapper: {e}")
    
    async def _execute_scheduled_workflow(self, schedule_id: str):
        """Execute a scheduled workflow."""
        import time
        
        print(f"[Scheduler] 🚀🚀🚀 _execute_scheduled_workflow started for {schedule_id}")
        
        schedule = self.schedules.get(schedule_id)
        if not schedule:
            print(f"[Scheduler] ❌ Schedule {schedule_id} not found")
            logger.warning(f"Schedule {schedule_id} not found")
            return
        
        if not schedule.enabled:
            print(f"[Scheduler] ⏸️ Schedule {schedule_id} is disabled, skipping")
            logger.info(f"Schedule {schedule_id} is disabled, skipping")
            return
        
        print(f"[Scheduler] 🚀 Executing scheduled workflow: {schedule.workflow_name}")
        logger.info(f"🚀 Executing scheduled workflow: {schedule.workflow_name}")
        
        # Mark as running
        start_time = time.time()
        schedule.last_run = datetime.utcnow().isoformat()
        schedule.last_status = "running"
        schedule.last_error = None
        if self.use_database:
            self._save_schedule_to_database(schedule)
        else:
            self._save_schedules()
        
        execution_success = False
        error_message = None
        result_text = None
        
        try:
            # Execute the workflow
            if self._workflow_executor:
                result = await self._workflow_executor(
                    workflow_name=schedule.workflow_name,
                    session_id=schedule.session_id,
                    timeout=schedule.timeout
                )
                
                # Check if workflow succeeded
                if result.get('success', False):
                    execution_success = True
                    result_text = result.get('result', 'Workflow completed successfully')
                    logger.info(f"✅ Scheduled workflow '{schedule.workflow_name}' completed successfully")
                else:
                    error_message = result.get('error', 'Workflow execution failed')
                    logger.error(f"❌ Scheduled workflow '{schedule.workflow_name}' failed: {error_message}")
            else:
                error_message = "No workflow executor configured"
                logger.warning(error_message)
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"❌ Error executing scheduled workflow '{schedule.workflow_name}': {e}")
        
        execution_time = time.time() - start_time
        
        # Update execution status
        schedule.run_count += 1
        
        if execution_success:
            schedule.last_status = "success"
            schedule.last_error = None
            schedule.success_count += 1
        else:
            schedule.last_status = "failed"
            schedule.last_error = error_message
            schedule.failure_count += 1
            
            # Handle retry logic if enabled
            if schedule.retry_on_failure and schedule.failure_count <= schedule.max_retries:
                logger.info(f"Will retry (failure {schedule.failure_count}/{schedule.max_retries})")
        
        # Check if max_runs limit reached (only count successful runs for the limit)
        if schedule.max_runs is not None and schedule.success_count >= schedule.max_runs:
            logger.info(f"⏹️  Schedule '{schedule.workflow_name}' reached max successful runs ({schedule.max_runs}), disabling")
            schedule.enabled = False
            # Remove from scheduler
            if self.scheduler and self.scheduler.get_job(schedule_id):
                self.scheduler.remove_job(schedule_id)
                logger.info(f"Removed job {schedule_id} from scheduler")
        
        # Update next run time (if still enabled)
        if schedule.enabled and self.scheduler:
            job = self.scheduler.get_job(schedule_id)
            if job and job.next_run_time:
                schedule.next_run = job.next_run_time.isoformat()
            else:
                schedule.next_run = None
        else:
            schedule.next_run = None
        
        # Store in run history
        end_time_iso = datetime.utcnow().isoformat()
        self._add_run_history(
            schedule_id=schedule_id,
            workflow_id=schedule.workflow_id,
            workflow_name=schedule.workflow_name,
            session_id=schedule.session_id,
            status="success" if execution_success else "failed",
            result=result_text,
            error=error_message,
            started_at=schedule.last_run,  # Stored earlier when execution started
            completed_at=end_time_iso,
            execution_time=execution_time
        )
        
        if self.use_database:
            self._save_schedule_to_database(schedule)
        else:
            self._save_schedules()
    
    # CRUD Operations
    
    def create_schedule(self, 
                       workflow_id: str,
                       workflow_name: str,
                       session_id: str,
                       schedule_type: ScheduleType,
                       **kwargs) -> ScheduledWorkflow:
        """Create a new scheduled workflow."""
        schedule = ScheduledWorkflow(
            id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            session_id=session_id,
            schedule_type=schedule_type,
            **kwargs
        )
        
        self.schedules[schedule.id] = schedule
        
        if self.use_database:
            self._save_schedule_to_database(schedule)
        else:
            self._save_schedules()
        
        print(f"[Scheduler] Created schedule {schedule.id}, enabled={schedule.enabled}, _is_running={self._is_running}")
        
        if schedule.enabled and self._is_running:
            print(f"[Scheduler] Adding job to APScheduler...")
            self._add_job_to_scheduler(schedule)
        else:
            print(f"[Scheduler] ⚠️ NOT adding job: enabled={schedule.enabled}, _is_running={self._is_running}")
        
        logger.info(f"Created schedule {schedule.id} for workflow '{workflow_name}'")
        return schedule
    
    def get_schedule(self, schedule_id: str) -> Optional[ScheduledWorkflow]:
        """Get a schedule by ID."""
        return self.schedules.get(schedule_id)
    
    def list_schedules(self, workflow_id: Optional[str] = None, session_id: Optional[str] = None) -> List[ScheduledWorkflow]:
        """List all schedules, optionally filtered by workflow and/or session."""
        schedules = list(self.schedules.values())
        if workflow_id:
            schedules = [s for s in schedules if s.workflow_id == workflow_id]
        if session_id:
            schedules = [s for s in schedules if s.session_id == session_id]
        return sorted(schedules, key=lambda s: s.created_at, reverse=True)
    
    def update_schedule(self, schedule_id: str, **kwargs) -> Optional[ScheduledWorkflow]:
        """Update a schedule."""
        schedule = self.schedules.get(schedule_id)
        if not schedule:
            return None
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(schedule, key):
                setattr(schedule, key, value)
        
        schedule.updated_at = datetime.utcnow().isoformat()
        
        if self.use_database:
            self._save_schedule_to_database(schedule)
        else:
            self._save_schedules()
        
        # Update scheduler job
        if self.scheduler and self._is_running:
            # Remove old job
            try:
                self.scheduler.remove_job(schedule_id)
            except:
                pass
            
            # Add updated job if enabled
            if schedule.enabled:
                self._add_job_to_scheduler(schedule)
        
        logger.info(f"Updated schedule {schedule_id}")
        return schedule
    
    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        if schedule_id not in self.schedules:
            return False
        
        # Remove from scheduler
        if self.scheduler and self._is_running:
            try:
                self.scheduler.remove_job(schedule_id)
            except:
                pass
        
        del self.schedules[schedule_id]
        
        if self.use_database:
            self._delete_schedule_from_database(schedule_id)
        else:
            self._save_schedules()
        
        logger.info(f"Deleted schedule {schedule_id}")
        return True
    
    def toggle_schedule(self, schedule_id: str, enabled: bool) -> Optional[ScheduledWorkflow]:
        """Enable or disable a schedule."""
        return self.update_schedule(schedule_id, enabled=enabled)
    
    def get_upcoming_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get upcoming scheduled runs across all workflows."""
        upcoming = []
        
        for schedule in self.schedules.values():
            if schedule.enabled and schedule.next_run:
                upcoming.append({
                    'schedule_id': schedule.id,
                    'workflow_id': schedule.workflow_id,
                    'workflow_name': schedule.workflow_name,
                    'next_run': schedule.next_run,
                    'schedule_type': schedule.schedule_type.value if isinstance(schedule.schedule_type, ScheduleType) else schedule.schedule_type
                })
        
        # Sort by next run time
        upcoming.sort(key=lambda x: x['next_run'])
        return upcoming[:limit]
    
    def get_run_history(self, schedule_id: Optional[str] = None, session_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get run history for schedules with full results, optionally filtered by session."""
        
        if self.use_database and self.db_conn:
            # Query from database
            try:
                cur = self.db_conn.cursor()
                
                # Build query with optional filters
                query = "SELECT * FROM schedule_run_history WHERE 1=1"
                params = []
                
                if schedule_id:
                    query += " AND schedule_id = %s"
                    params.append(schedule_id)
                
                if session_id:
                    query += " AND session_id = %s"
                    params.append(session_id)
                
                query += " ORDER BY timestamp DESC LIMIT %s"
                params.append(limit)
                
                cur.execute(query, params)
                rows = cur.fetchall()
                cur.close()
                
                # Convert to list of dicts
                history = []
                for row in rows:
                    entry = {
                        "run_id": str(row[0]),
                        "schedule_id": str(row[1]),
                        "workflow_id": row[2],
                        "workflow_name": row[3],
                        "session_id": row[4],
                        "timestamp": row[5].isoformat() if row[5] else None,
                        "started_at": row[6].isoformat() if row[6] else None,
                        "completed_at": row[7].isoformat() if row[7] else None,
                        "duration_seconds": row[8],
                        "status": row[9],
                        "result": row[10],
                        "error": row[11]
                    }
                    history.append(entry)
                
                return history
                
            except Exception as e:
                logger.error(f"Error querying run history from database: {e}")
                return []
        else:
            # Fallback to in-memory list
            filtered = self.run_history
            
            if schedule_id:
                # Filter by schedule_id
                filtered = [h for h in filtered if h.get('schedule_id') == schedule_id]
            
            if session_id:
                # Filter by session_id (owner of the schedule)
                filtered = [h for h in filtered if h.get('session_id') == session_id]
            
            # Sort by timestamp descending and limit
            sorted_history = sorted(filtered, key=lambda x: x.get('timestamp', ''), reverse=True)
            return sorted_history[:limit]


# Global scheduler instance
_scheduler: Optional[WorkflowScheduler] = None


def get_workflow_scheduler() -> WorkflowScheduler:
    """Get the global workflow scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = WorkflowScheduler()
    return _scheduler


async def initialize_scheduler(workflow_executor: Callable) -> WorkflowScheduler:
    """Initialize and start the workflow scheduler."""
    scheduler = get_workflow_scheduler()
    scheduler.set_workflow_executor(workflow_executor)
    await scheduler.start()
    return scheduler
