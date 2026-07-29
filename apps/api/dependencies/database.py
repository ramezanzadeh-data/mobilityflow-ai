from db.database import get_db_connection


def get_db():
    """
    FastAPI dependency form of the shared pooled connection. Routes in
    this codebase currently call db.database's functions directly
    rather than taking a raw connection, but this stays available for
    any endpoint that needs one (e.g. a custom multi-statement query).
    """
    with get_db_connection() as conn:
        yield conn
