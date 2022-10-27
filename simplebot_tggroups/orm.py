"""database"""

from contextlib import contextmanager
from threading import Lock

from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import sessionmaker


# pylama:ignore=R0903
class Base:
    @declared_attr
    def __tablename__(cls):  # noqa
        return cls.__name__.lower()  # noqa


Base = declarative_base(cls=Base)  # noqa
_Session = sessionmaker()
_lock = Lock()


class Link(Base):
    dcchat = Column(Integer, primary_key=True)
    tgchat = Column(Integer)


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    with _lock:
        session = _Session()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()


def init(path: str, debug: bool = False) -> None:
    """Initialize engine."""
    engine = create_engine(path, echo=debug)
    Base.metadata.create_all(engine)  # noqa
    _Session.configure(bind=engine)
