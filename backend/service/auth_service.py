"""Authentication Service Module

This module provides user authentication and JWT token management.
It's deliberately kept lightweight with minimal dependencies to enable
fast startup of the WebSocket server.
"""

import os
import json
import hashlib
from datetime import datetime, timedelta, UTC
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import jwt

# Authentication constants
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

# Default data directory
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class User:
    user_id: str
    email: str
    password_hash: str
    name: str
    role: str
    description: str
    skills: List[str]
    color: str
    created_at: datetime
    last_login: Optional[datetime] = None


class AuthService:
    """Handles user authentication and JWT token management using JSON file storage."""
    
    def __init__(self, users_file: Path | str = None):
        if users_file is None:
            users_file = DEFAULT_DATA_DIR / "users.json"
        self.users_file = Path(users_file)
        self.users: Dict[str, User] = {}
        # Track active WebSocket connections for logging (not used for data retrieval)
        # Each session manages its own user info via WebSocket
        self.active_users: Dict[str, Dict[str, Any]] = {}
        
        # Ensure data directory exists
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load users from JSON file
        self._load_users_from_file()
    
    def _load_users_from_file(self):
        """Load users from JSON file."""
        try:
            with open(self.users_file, 'r') as f:
                data = json.load(f)
                for user_data in data.get('users', []):
                    user = User(
                        user_id=user_data['user_id'],
                        email=user_data['email'],
                        password_hash=user_data['password_hash'],
                        name=user_data['name'],
                        role=user_data.get('role', ''),
                        description=user_data.get('description', ''),
                        skills=user_data.get('skills', []),
                        color=user_data.get('color', '#6B7280'),
                        created_at=datetime.fromisoformat(user_data['created_at'].replace('Z', '+00:00')),
                        last_login=datetime.fromisoformat(user_data['last_login'].replace('Z', '+00:00')) if user_data.get('last_login') else None
                    )
                    self.users[user.email] = user
            print(f"[AuthService] Loaded {len(self.users)} users from {self.users_file}")
        except FileNotFoundError:
            print(f"[AuthService] Users file {self.users_file} not found, creating with default users")
            self._create_default_users_file()
        except json.JSONDecodeError as e:
            print(f"[AuthService] Error parsing {self.users_file}: {e}")
            self._create_default_users_file()
        except Exception as e:
            print(f"[AuthService] Error loading users: {e}")
            self._create_default_users_file()
    
    def _create_default_users_file(self):
        """Create default users file with test users."""
        default_users = [
            {"email": "simon@example.com", "password": "simon123", "name": "Simon", "role": "Product Manager", "description": "Experienced product manager with focus on AI and automation tools", "skills": ["Product Strategy", "User Research", "Agile Development", "AI/ML Products"], "color": "#3B82F6"},
            {"email": "admin@example.com", "password": "admin123", "name": "Admin", "role": "System Administrator", "description": "Full system administrator with expertise in cloud infrastructure and security", "skills": ["System Administration", "Cloud Architecture", "Security", "DevOps"], "color": "#EF4444"},
            {"email": "test@example.com", "password": "test123", "name": "Test User", "role": "Software Developer", "description": "Full-stack developer specializing in web applications and APIs", "skills": ["JavaScript", "Python", "React", "Node.js", "API Development"], "color": "#10B981"},
        ]
        
        users_data = {"users": []}
        for i, user_data in enumerate(default_users, 1):
            password_hash = self._hash_password(user_data["password"])
            user_record = {
                "user_id": f"user_{i}",
                "email": user_data["email"],
                "password_hash": password_hash,
                "name": user_data["name"],
                "role": user_data["role"],
                "description": user_data["description"],
                "skills": user_data["skills"],
                "color": user_data["color"],
                "created_at": datetime.now(UTC).isoformat().replace('+00:00', 'Z'),
                "last_login": None
            }
            users_data["users"].append(user_record)
            
            # Also add to memory
            user = User(
                user_id=user_record["user_id"],
                email=user_record["email"],
                password_hash=password_hash,
                name=user_record["name"],
                role=user_record["role"],
                description=user_record["description"],
                skills=user_record["skills"],
                color=user_record["color"],
                created_at=datetime.now(UTC)
            )
            self.users[user.email] = user
        
        # Save to file
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f, indent=2)
        print(f"[AuthService] Created {self.users_file} with {len(default_users)} default users")
    
    def _save_users_to_file(self):
        """Save current users to JSON file."""
        users_data = {"users": []}
        for user in self.users.values():
            user_record = {
                "user_id": user.user_id,
                "email": user.email,
                "password_hash": user.password_hash,
                "name": user.name,
                "role": user.role,
                "description": user.description,
                "skills": user.skills,
                "color": user.color,
                "created_at": user.created_at.isoformat().replace('+00:00', 'Z'),
                "last_login": user.last_login.isoformat().replace('+00:00', 'Z') if user.last_login else None
            }
            users_data["users"].append(user_record)
        
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f, indent=2)
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA-256."""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def create_user(self, email: str, password: str, name: str, role: str = "User", description: str = "", skills: List[str] = None, color: str = "#6B7280") -> Optional[User]:
        """Create a new user and save to file."""
        if email in self.users:
            return None
            
        user_id = f"user_{len(self.users) + 1}"
        password_hash = self._hash_password(password)
        
        user = User(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            name=name,
            role=role,
            description=description,
            skills=skills or [],
            color=color,
            created_at=datetime.now(UTC)
        )
        
        self.users[email] = user
        # Save to file whenever a new user is created
        self._save_users_to_file()
        return user
    
    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user with email and password - always reads from JSON file."""
        # Always reload users from file to get latest data
        self._load_users_from_file()
        
        user = self.users.get(email)
        if not user:
            return None
            
        password_hash = self._hash_password(password)
        if password_hash != user.password_hash:
            return None
            
        # Update last login and save to file
        user.last_login = datetime.now(UTC)
        self._save_users_to_file()
        return user
    
    def create_access_token(self, user: User, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token for a user."""
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=24)
            
        to_encode = {
            "sub": user.email,
            "user_id": user.user_id,
            "name": user.name,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token - always reads from JSON file."""
        try:
            print(f"[AuthService] Verifying token...")
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: str = payload.get("sub")
            user_id: str = payload.get("user_id")
            print(f"[AuthService] Token decoded - email: {email}, user_id: {user_id}")
            
            if email is None:
                print(f"[AuthService] Token verification failed: no email in payload")
                return None
                
            # Always reload users from file to get latest data
            self._load_users_from_file()
            
            # Check if user still exists
            user = self.users.get(email)
            if user is None:
                print(f"[AuthService] Token verification failed: user {email} not found in users database")
                return None
            
            print(f"[AuthService] Token verified successfully for user: {email}")
            return {
                "user_id": payload.get("user_id"),
                "email": email,
                "name": payload.get("name"),
                "exp": payload.get("exp")
            }
        except jwt.ExpiredSignatureError:
            return None
        except jwt.JWTError:
            return None
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return self.users.get(email)
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users (without password hashes)."""
        return [
            {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "description": user.description,
                "skills": user.skills,
                "color": user.color,
                "created_at": user.created_at.isoformat(),
                "last_login": user.last_login.isoformat() if user.last_login else None
            }
            for user in self.users.values()
        ]
    
    def add_active_user(self, user_data: Dict[str, Any]):
        """Add a user to the active users list."""
        user_id = user_data.get("user_id")
        if user_id:
            self.active_users[user_id] = user_data
            print(f"[AuthService] Added active user: {user_data.get('name', 'Unknown')} ({user_data.get('email', 'No email')})")
    
    def remove_active_user(self, user_data: Dict[str, Any]):
        """Remove a user from the active users list (for logging purposes)."""
        user_id = user_data.get("user_id")
        if user_id and user_id in self.active_users:
            removed_user = self.active_users.pop(user_id)
            print(f"[AuthService] Removed active user: {removed_user.get('name', 'Unknown')} ({removed_user.get('email', 'No email')})")
