"""Collaborative Sessions Management

This module manages collaborative sessions where multiple users can work together
in the same conversation context, seeing all messages, agent responses, and files
in real-time.

Key concepts:
- Session Owner: The user who started the session
- Session Members: All users currently in the session (including owner)
- Pending Invitations: Invitations that haven't been accepted/declined yet
"""

import time
import logging
from typing import Dict, Any, List, Set, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SessionInvitation:
    """Represents a pending session invitation."""
    invitation_id: str
    session_id: str  # The tenant/session ID to join
    from_user_id: str
    from_user_name: str
    to_user_id: str
    to_user_name: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 300)  # 5 min expiry
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "invitation_id": self.invitation_id,
            "session_id": self.session_id,
            "from_user_id": self.from_user_id,
            "from_user_name": self.from_user_name,
            "to_user_id": self.to_user_id,
            "to_user_name": self.to_user_name,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "expires_in_seconds": max(0, int(self.expires_at - time.time()))
        }


@dataclass
class CollaborativeSession:
    """Represents an active collaborative session."""
    session_id: str  # The tenant/session ID
    owner_user_id: str
    owner_user_name: str
    member_user_ids: Set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    current_conversation_id: Optional[str] = None  # Track the current conversation for auto-navigation
    
    def add_member(self, user_id: str):
        self.member_user_ids.add(user_id)
    
    def remove_member(self, user_id: str):
        self.member_user_ids.discard(user_id)
    
    def is_member(self, user_id: str) -> bool:
        return user_id in self.member_user_ids or user_id == self.owner_user_id
    
    def get_all_member_ids(self) -> Set[str]:
        """Get all members including owner."""
        return self.member_user_ids | {self.owner_user_id}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "owner_user_id": self.owner_user_id,
            "owner_user_name": self.owner_user_name,
            "member_user_ids": list(self.member_user_ids),
            "all_member_ids": list(self.get_all_member_ids()),
            "created_at": self.created_at,
            "current_conversation_id": self.current_conversation_id
        }


class CollaborativeSessionManager:
    """Manages collaborative sessions and invitations."""
    
    def __init__(self):
        # Pending invitations: invitation_id -> SessionInvitation
        self.pending_invitations: Dict[str, SessionInvitation] = {}
        # Invitations by recipient: to_user_id -> list of invitation_ids
        self.invitations_by_user: Dict[str, List[str]] = {}
        # Active collaborative sessions: session_id -> CollaborativeSession
        self.active_sessions: Dict[str, CollaborativeSession] = {}
        # User to sessions mapping: user_id -> set of session_ids they're in
        self.user_sessions: Dict[str, Set[str]] = {}
        
    def create_invitation(
        self,
        session_id: str,
        from_user_id: str,
        from_user_name: str,
        to_user_id: str,
        to_user_name: str
    ) -> SessionInvitation:
        """Create a new session invitation."""
        import uuid
        
        # Clean up expired invitations first
        self._cleanup_expired_invitations()
        
        # Check if there's already a pending invitation
        existing = self._find_existing_invitation(session_id, from_user_id, to_user_id)
        if existing:
            logger.info(f"Invitation already exists: {existing.invitation_id}")
            return existing
        
        invitation_id = f"inv_{uuid.uuid4().hex[:12]}"
        invitation = SessionInvitation(
            invitation_id=invitation_id,
            session_id=session_id,
            from_user_id=from_user_id,
            from_user_name=from_user_name,
            to_user_id=to_user_id,
            to_user_name=to_user_name
        )
        
        self.pending_invitations[invitation_id] = invitation
        
        if to_user_id not in self.invitations_by_user:
            self.invitations_by_user[to_user_id] = []
        self.invitations_by_user[to_user_id].append(invitation_id)
        
        logger.info(f"Created invitation {invitation_id}: {from_user_name} -> {to_user_name}")
        return invitation
    
    def get_invitation(self, invitation_id: str) -> Optional[SessionInvitation]:
        """Get an invitation by ID."""
        invitation = self.pending_invitations.get(invitation_id)
        if invitation and invitation.is_expired():
            self._remove_invitation(invitation_id)
            return None
        return invitation
    
    def get_pending_invitations_for_user(self, user_id: str) -> List[SessionInvitation]:
        """Get all pending invitations for a user."""
        self._cleanup_expired_invitations()
        invitation_ids = self.invitations_by_user.get(user_id, [])
        return [
            self.pending_invitations[inv_id]
            for inv_id in invitation_ids
            if inv_id in self.pending_invitations
        ]
    
    def accept_invitation(self, invitation_id: str, user_id: str) -> Optional[CollaborativeSession]:
        """Accept an invitation and join the session."""
        invitation = self.get_invitation(invitation_id)
        if not invitation:
            logger.warning(f"Invitation not found or expired: {invitation_id}")
            return None
        
        if invitation.to_user_id != user_id:
            logger.warning(f"User {user_id} cannot accept invitation meant for {invitation.to_user_id}")
            return None
        
        # Get or create the collaborative session
        session = self._get_or_create_session(
            invitation.session_id,
            invitation.from_user_id,
            invitation.from_user_name
        )
        
        # Add the user to the session
        session.add_member(user_id)
        self._track_user_session(user_id, session.session_id)
        
        # Remove the invitation
        self._remove_invitation(invitation_id)
        
        logger.info(f"User {user_id} joined session {session.session_id}")
        return session
    
    def decline_invitation(self, invitation_id: str, user_id: str) -> bool:
        """Decline an invitation."""
        invitation = self.get_invitation(invitation_id)
        if not invitation:
            return False
        
        if invitation.to_user_id != user_id:
            return False
        
        self._remove_invitation(invitation_id)
        logger.info(f"User {user_id} declined invitation {invitation_id}")
        return True
    
    def leave_session(self, session_id: str, user_id: str) -> bool:
        """Remove a user from a collaborative session."""
        session = self.active_sessions.get(session_id)
        if not session:
            return False
        
        if user_id == session.owner_user_id:
            # Owner leaving - end the session for everyone
            self._end_session(session_id)
            return True
        
        session.remove_member(user_id)
        self._untrack_user_session(user_id, session_id)
        
        logger.info(f"User {user_id} left session {session_id}")
        return True
    
    def get_session(self, session_id: str) -> Optional[CollaborativeSession]:
        """Get a collaborative session by ID."""
        return self.active_sessions.get(session_id)
    
    def get_session_members(self, session_id: str) -> List[str]:
        """Get all member user IDs for a session."""
        session = self.active_sessions.get(session_id)
        if not session:
            return []
        return list(session.get_all_member_ids())
    
    def is_collaborative_session(self, session_id: str) -> bool:
        """Check if a session has multiple users."""
        session = self.active_sessions.get(session_id)
        return session is not None and len(session.get_all_member_ids()) > 1
    
    def get_user_sessions(self, user_id: str) -> List[str]:
        """Get all session IDs a user is part of."""
        return list(self.user_sessions.get(user_id, set()))
    
    def _get_or_create_session(
        self,
        session_id: str,
        owner_user_id: str,
        owner_user_name: str
    ) -> CollaborativeSession:
        """Get existing session or create new one."""
        if session_id not in self.active_sessions:
            session = CollaborativeSession(
                session_id=session_id,
                owner_user_id=owner_user_id,
                owner_user_name=owner_user_name
            )
            self.active_sessions[session_id] = session
            self._track_user_session(owner_user_id, session_id)
            logger.info(f"Created collaborative session: {session_id}")
        return self.active_sessions[session_id]
    
    def _track_user_session(self, user_id: str, session_id: str):
        """Track that a user is in a session."""
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = set()
        self.user_sessions[user_id].add(session_id)
    
    def _untrack_user_session(self, user_id: str, session_id: str):
        """Remove session from user's tracking."""
        if user_id in self.user_sessions:
            self.user_sessions[user_id].discard(session_id)
    
    def update_current_conversation(self, session_id: str, conversation_id: str) -> bool:
        """Update the current conversation for a session.
        
        This is called when a user creates or switches to a new conversation.
        Allows other members to auto-navigate when joining.
        """
        session = self.active_sessions.get(session_id)
        if session:
            session.current_conversation_id = conversation_id
            logger.info(f"Updated current conversation for session {session_id[:8]}... to {conversation_id[:8]}...")
            return True
        return False
    
    def get_current_conversation(self, session_id: str) -> Optional[str]:
        """Get the current conversation for a session."""
        session = self.active_sessions.get(session_id)
        if session:
            return session.current_conversation_id
        return None
    
    def _end_session(self, session_id: str):
        """End a collaborative session."""
        session = self.active_sessions.pop(session_id, None)
        if session:
            # Remove session from all users' tracking
            for user_id in session.get_all_member_ids():
                self._untrack_user_session(user_id, session_id)
            logger.info(f"Ended collaborative session: {session_id}")
    
    def _find_existing_invitation(
        self,
        session_id: str,
        from_user_id: str,
        to_user_id: str
    ) -> Optional[SessionInvitation]:
        """Find an existing invitation matching the parameters."""
        for invitation in self.pending_invitations.values():
            if (invitation.session_id == session_id and
                invitation.from_user_id == from_user_id and
                invitation.to_user_id == to_user_id and
                not invitation.is_expired()):
                return invitation
        return None
    
    def _remove_invitation(self, invitation_id: str):
        """Remove an invitation."""
        invitation = self.pending_invitations.pop(invitation_id, None)
        if invitation and invitation.to_user_id in self.invitations_by_user:
            try:
                self.invitations_by_user[invitation.to_user_id].remove(invitation_id)
            except ValueError:
                pass
    
    def _cleanup_expired_invitations(self):
        """Remove all expired invitations."""
        expired = [
            inv_id for inv_id, inv in self.pending_invitations.items()
            if inv.is_expired()
        ]
        for inv_id in expired:
            self._remove_invitation(inv_id)
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired invitations")


def get_online_users_from_connections(
    user_connections: Dict[str, Set],
    authenticated_connections: Dict,
    exclude_user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get list of online users from WebSocket connections.
    
    This is a helper function that works with WebSocketManager's connection tracking.
    
    Args:
        user_connections: Dict mapping user_id to set of WebSocket connections
        authenticated_connections: Dict mapping WebSocket to AuthenticatedConnection
        exclude_user_id: Optional user ID to exclude from results (typically the requester)
    
    Returns:
        List of user dictionaries with id, username, and email
    """
    online_users = []
    seen_user_ids = set()
    
    for ws, auth_conn in authenticated_connections.items():
        user_id = auth_conn.user_data.get('user_id')
        if user_id and user_id not in seen_user_ids:
            if exclude_user_id and user_id == exclude_user_id:
                continue
            seen_user_ids.add(user_id)
            online_users.append({
                'user_id': user_id,
                'username': auth_conn.username,
                'email': auth_conn.user_data.get('email', '')
            })
    
    return online_users


# Global singleton instance
_session_manager: Optional[CollaborativeSessionManager] = None


def get_session_manager() -> CollaborativeSessionManager:
    """Get the global collaborative session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = CollaborativeSessionManager()
    return _session_manager
