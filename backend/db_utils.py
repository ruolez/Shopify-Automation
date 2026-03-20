"""
Database utility functions for PostgreSQL and SQLite compatibility
"""
import os
from sqlalchemy import func, text
from sqlalchemy.sql import expression
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import DateTime, TypeDecorator
from datetime import datetime


def get_db_type():
    """Get the current database type from DATABASE_URL"""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    if "postgresql" in db_url or "postgres" in db_url:
        return "postgresql"
    return "sqlite"


def concat_db(*args):
    """
    Database-agnostic concatenation function
    Returns appropriate concatenation based on database type
    """
    db_type = get_db_type()
    if db_type == "postgresql":
        # PostgreSQL uses || operator or string concatenation
        result = args[0]
        for arg in args[1:]:
            result = result + arg
        return result
    else:
        # SQLite uses || or the concat function
        return func.concat(*args)


def distinct_count(column):
    """
    Database-agnostic distinct count
    """
    return func.count(func.distinct(column))


class utcnow(expression.FunctionElement):
    """Database-agnostic UTC now function"""
    type = DateTime()
    inherit_cache = True


@compiles(utcnow, 'postgresql')
def pg_utcnow(element, compiler, **kw):
    """PostgreSQL UTC now"""
    return "TIMEZONE('utc', CURRENT_TIMESTAMP)"


@compiles(utcnow, 'sqlite')
def sqlite_utcnow(element, compiler, **kw):
    """SQLite UTC now"""
    return "DATETIME('now')"


def check_table_exists(connection, table_name):
    """
    Check if a table exists in the database
    """
    db_type = get_db_type()
    
    if db_type == "postgresql":
        query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = :table_name
            )
        """)
    else:
        query = text("""
            SELECT COUNT(*) > 0
            FROM sqlite_master 
            WHERE type='table' AND name=:table_name
        """)
    
    result = connection.execute(query, {"table_name": table_name})
    return result.scalar()


def check_column_exists(connection, table_name, column_name):
    """
    Check if a column exists in a table
    """
    db_type = get_db_type()
    
    if db_type == "postgresql":
        query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = :table_name 
                AND column_name = :column_name
            )
        """)
    else:
        query = text("""
            SELECT COUNT(*) > 0
            FROM pragma_table_info(:table_name) 
            WHERE name=:column_name
        """)
    
    result = connection.execute(query, {
        "table_name": table_name,
        "column_name": column_name
    })
    return result.scalar()


def get_date_trunc(precision, column):
    """
    Database-agnostic date truncation
    precision: 'day', 'month', 'year', 'hour', etc.
    """
    db_type = get_db_type()
    
    if db_type == "postgresql":
        return func.date_trunc(precision, column)
    else:
        # SQLite doesn't have date_trunc, use date() for day precision
        if precision == 'day':
            return func.date(column)
        elif precision == 'month':
            return func.strftime('%Y-%m-01', column)
        elif precision == 'year':
            return func.strftime('%Y-01-01', column)
        else:
            return column


def case_insensitive_compare(column, value):
    """
    Database-agnostic case-insensitive comparison
    """
    db_type = get_db_type()
    
    if db_type == "postgresql":
        return func.lower(column) == func.lower(value)
    else:
        # SQLite is case-insensitive by default for LIKE
        return column == value