from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3

def init_db():
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()

    # TIMETABLE TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class TEXT,
        day TEXT,
        period INTEGER,
        subject TEXT,
        teacher TEXT,
        substitute TEXT
    )
    """)

    # ✅ ADD THIS (TEACHERS TABLE)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    # ✅ ADD THIS (ADMIN TABLE)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    email TEXT,
    otp TEXT,
    otp_expiry TEXT
    )
    """)

    # ✅ DEFAULT ADMIN
    cur.execute("SELECT * FROM admin WHERE username='admin'")
    if not cur.fetchone():
        cur.execute("INSERT INTO admin (username, password) VALUES (?, ?)", ('admin', '1234'))

    conn.commit()
    conn.close()