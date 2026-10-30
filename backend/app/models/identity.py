import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None]
    full_name: Mapped[str] = mapped_column(String(200), default="")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    mfa_secret_encrypted: Mapped[str | None]
    mfa_enabled: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_state: Mapped[dict] = mapped_column(default=dict)


class Organization(IdMixin, TimestampMixin, Base):
    """The paying account: a single business, or an agency that serves many clients."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # business | agency
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # White-label settings used on agency reports: logo_url, primary_color, footer.
    white_label: Mapped[dict] = mapped_column(default=dict)

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="organization")


class OrganizationMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # owner and admin get access to every workspace of the organization;
    # member only gets the workspaces they are explicitly added to.
    role: Mapped[str] = mapped_column(String(20), default="member")


class Workspace(IdMixin, TimestampMixin, Base):
    """The tenant. Every business record carries a workspace_id."""

    __tablename__ = "workspaces"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # business | agency | client
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    industry: Mapped[str | None] = mapped_column(String(120))
    # Approval policies and spend limits, see app.services.policy.DEFAULT_WORKSPACE_SETTINGS.
    settings: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | pending_deletion
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(back_populates="workspaces")


class WorkspaceMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40))


class Invitation(IdMixin, TimestampMixin, Base):
    """A membership for an email that has no account yet; applied when that email registers."""

    __tablename__ = "invitations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(40))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))


class OneTimeToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "one_time_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))  # verify_email | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
