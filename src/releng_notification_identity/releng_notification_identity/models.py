from backend_common.db import db
from .config import CHANNELS, PROJECT_NAME, URGENCY_LEVELS
from sqlalchemy import Column, Enum, ForeignKey, Integer, String, UniqueConstraint


class Identity(db.Model):
    __tablename__ = PROJECT_NAME + '-identities'

    id = Column(Integer, primary_key=True)
    name = Column(String(32), unique=True)


class Preference(db.Model):
    __tablename__ = PROJECT_NAME + '-preferences'
    __table_args__ = (UniqueConstraint('identity', 'urgency', name='_one_urgency_per_id'),)

    id = Column(Integer, primary_key=True)
    urgency = Column(Enum(*URGENCY_LEVELS, name='notification-urgency-levels'), nullable=False)
    channel = Column(Enum(*CHANNELS, name='notification-channels'), nullable=False)
    target = Column(String, nullable=False)
    identity = Column(Integer, ForeignKey(Identity.id, ondelete='CASCADE', onupdate='CASCADE'), nullable=False)

    def to_dict(self):
        return {
            'urgency': self.urgency,
            'channel': self.channel,
            'target': self.target,
        }
