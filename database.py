import sqlite3
from datetime import datetime
from config import DATABASE_FILE


def create_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    return conn


def create_table(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY,
            text TEXT,
            processed_text TEXT,
            image_path TEXT,
            status TEXT,
            created_at TIMESTAMP,
            scheduled_at TIMESTAMP
        )
    """
    )
    conn.commit()


def initialize_database():
    conn = create_connection()
    create_table(conn)
    conn.close()


def add_article(text, processed_text, image_path=None):
    conn = create_connection()
    cursor = conn.cursor()
    status = "queued"
    created_at = datetime.now()
    cursor.execute(
        """
        INSERT INTO articles (text, processed_text, image_path, status, created_at)
        VALUES (?, ?, ?, ?, ?)
    """,
        (text, processed_text, image_path, status, created_at),
    )
    conn.commit()
    conn.close()


def get_queued_articles():
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM articles WHERE status = 'queued'")
    articles = cursor.fetchall()
    conn.close()
    return articles


def get_article_by_id(article_id):
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM articles WHERE id = ? AND status = 'queued'", (article_id,)
    )
    article = cursor.fetchone()
    conn.close()
    return article


def delete_article(article_id):
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE articles SET status = 'deleted' WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()


def update_time_scheduled(article_id, scheduled_at):
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE articles SET scheduled_at = ? WHERE id = ?", (scheduled_at, article_id)
    )
    conn.commit()
    conn.close()
