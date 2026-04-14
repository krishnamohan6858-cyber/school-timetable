from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import smtplib
import random
import os
import bcrypt
from email.mime.text import MIMEText
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret")

# ---------------- DATABASE ----------------

# def get_db_connection():
#     DATABASE_URL = os.environ.get("DATABASE_URL")

#     if DATABASE_URL:
#         return psycopg2.connect(DATABASE_URL)
#     else:
#         return psycopg2.connect(
#             host="localhost",
#             database="school_timetable",
#             user="postgres",
#             password="Triplet@5714"  # 👈 put your pgAdmin password
#         )


def get_db_connection():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

# ---------------- EMAIL ----------------

def send_otp(email, otp):
    sender = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")

    msg = MIMEText(f"Your OTP is: {otp}")
    msg['Subject'] = "Password Reset OTP"
    msg['From'] = sender
    msg['To'] = email

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(sender, password)
    server.send_message(msg)
    server.quit()

# ---------------- INIT DB ----------------

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS timetable (
        id SERIAL PRIMARY KEY,
        class TEXT,
        day TEXT,
        period INTEGER,
        subject TEXT,
        teacher TEXT,
        substitute TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        email TEXT,
        otp TEXT,
        otp_expiry TIMESTAMP
    )
    """)

    # Default admin (hashed password)
    cur.execute("SELECT * FROM admin WHERE username='admin'")
    if not cur.fetchone():
        hashed = bcrypt.hashpw("1234".encode(), bcrypt.gensalt()).decode()
        cur.execute(
            "INSERT INTO admin (username, password, email) VALUES (%s, %s, %s)",
            ('admin', hashed, 'your_email@gmail.com')
        )

    conn.commit()
    conn.close()

init_db()

# ---------------- HELPER ----------------

def get_teacher_load(day):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT teacher, COUNT(*) FROM timetable
    WHERE day=%s GROUP BY teacher
    """, (day,))

    data = cur.fetchall()
    conn.close()
    return dict(data)


def get_substitute(day, period):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT teacher FROM timetable")
    all_teachers = [t[0] for t in cur.fetchall()]

    cur.execute("SELECT teacher FROM timetable WHERE day=%s AND period=%s", (day, period))
    busy = [t[0] for t in cur.fetchall()]

    free = [t for t in all_teachers if t not in busy]
    loads = get_teacher_load(day)

    best = None
    min_load = 999

    for t in free:
        load = loads.get(t, 0)
        if load < 5 and load < min_load:
            best = t
            min_load = load

    conn.close()
    return best if best else "No substitute available"

# ---------------- ROUTES ----------------

@app.route('/')
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT name FROM teachers")
    teachers = [t[0] for t in cur.fetchall()]

    conn.close()
    return render_template('index.html', teachers=teachers)


@app.route('/timetable')
def timetable():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM timetable")
    data = cur.fetchall()

    conn.close()
    return render_template('timetable.html', data=data)


# @app.route('/add', methods=['POST'])
# def add():
#     class_name = request.form['class'].strip()
#     if not class_name:
#         flash("Invalid input", "error")
#         return redirect('/')

#     conn = get_db_connection()
#     cur = conn.cursor()

#     cur.execute("""
#     INSERT INTO timetable (class, day, period, subject, teacher, substitute)
#     VALUES (%s, %s, %s, %s, %s, %s)
#     """, (
#         class_name,
#         request.form['day'],
#         request.form['period'],
#         request.form['subject'],
#         request.form['teacher'],
#         ""
#     ))

#     conn.commit()
#     conn.close()

#     flash("Entry added successfully!", "success")
#     return redirect('/')

@app.route('/add', methods=['POST'])
def add():
    class_name = request.form['class'].strip()
    day = request.form['day']
    period = request.form['period']
    subject = request.form['subject']
    teacher = request.form['teacher']

    conn = get_db_connection()
    cur = conn.cursor()

    # ❌ Check 1: Class already assigned
    cur.execute("""
    SELECT * FROM timetable
    WHERE class=%s AND day=%s AND period=%s
    """, (class_name, day, period))

    if cur.fetchone():
        conn.close()
        flash("⚠️ This class already has a subject assigned in this period!", "error")
        return redirect('/')

    # ❌ Check 2: Teacher already busy
    cur.execute("""
    SELECT * FROM timetable
    WHERE teacher=%s AND day=%s AND period=%s
    """, (teacher, day, period))

    if cur.fetchone():
        conn.close()
        flash("⚠️ This teacher already has a class in this period!", "error")
        return redirect('/')

    # ✅ Insert if valid
    cur.execute("""
    INSERT INTO timetable (class, day, period, subject, teacher, substitute)
    VALUES (%s, %s, %s, %s, %s, %s)
    """, (class_name, day, period, subject, teacher, ""))

    conn.commit()
    conn.close()

    flash("✅ Entry added successfully!", "success")
    return redirect('/')


@app.route('/absent', methods=['POST'])
def mark_absent():
    day = request.form['day']
    period = int(request.form['period'])
    teacher = request.form['teacher']

    substitute = get_substitute(day, period)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    UPDATE timetable
    SET substitute=%s
    WHERE day=%s AND period=%s AND teacher=%s
    """, (substitute, day, period, teacher))

    conn.commit()
    conn.close()

    flash(f"Substitute assigned: {substitute}", "success")
    return redirect('/timetable')


# ---------------- LOGIN ----------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT teacher FROM timetable")
    teachers = [t[0] for t in cur.fetchall()]

    error = None

    if request.method == 'POST':
        teacher = request.form['teacher']
        if teacher in teachers:
            session['teacher'] = teacher
            return redirect('/dashboard')
        else:
            error = "Teacher not found"

    conn.close()
    return render_template('login.html', teachers=teachers, error=error)


@app.route('/dashboard')
def dashboard():
    if 'teacher' not in session:
        return redirect('/login')

    name = session['teacher']

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT day, period, subject, class, substitute
    FROM timetable
    WHERE teacher=%s OR substitute=%s
    """, (name, name))

    timetable = cur.fetchall()
    conn.close()

    return render_template('teacher.html', timetable=timetable, teacher=name)


# ---------------- ADMIN ----------------

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    conn = get_db_connection()
    cur = conn.cursor()

    error = None

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cur.execute("SELECT password FROM admin WHERE username=%s", (username,))
        data = cur.fetchone()

        if data and bcrypt.checkpw(password.encode(), data[0].encode()):
            session['admin'] = username
            return redirect('/admin-dashboard')
        else:
            error = "Invalid credentials"

    conn.close()
    return render_template('admin_login.html', error=error)

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
    if 'admin' not in session:
        return redirect('/admin-login')

    name = request.form['name'].strip()

    if not name:
        flash("Teacher name cannot be empty", "error")
        return redirect('/admin-dashboard')

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("INSERT INTO teachers (name) VALUES (%s)", (name,))
        conn.commit()
        flash("✅ Teacher added successfully!", "success")
    except:
        flash("⚠️ Teacher already exists!", "error")

    conn.close()
    return redirect('/admin-dashboard')


@app.route('/admin-dashboard')
def admin_dashboard():
    if 'admin' not in session:
        # return redirect('/admin-login')
        return redirect('/admin-login')
    return render_template('admin_dashboard.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ---------------- OTP RESET ----------------

@app.route('/send-otp', methods=['POST'])
def send_otp_route():
    username = request.form['username']

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT email FROM admin WHERE username=%s", (username,))
    data = cur.fetchone()

    if data:
        email = data[0]
        otp = str(random.randint(100000, 999999))
        expiry = datetime.now() + timedelta(minutes=5)

        cur.execute("""
        UPDATE admin SET otp=%s, otp_expiry=%s WHERE username=%s
        """, (otp, expiry, username))

        conn.commit()
        send_otp(email, otp)

        return render_template('verify_otp.html', username=username)

    return "Username not found"


@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    username = request.form['username']
    user_otp = request.form['otp']
    new_password = request.form['new_password']

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT otp, otp_expiry FROM admin WHERE username=%s", (username,))
    data = cur.fetchone()

    if data:
        otp, expiry = data

        if datetime.now() > expiry:
            return "OTP expired"

        if user_otp == otp:
            hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
            cur.execute("""
            UPDATE admin SET password=%s, otp=NULL WHERE username=%s
            """, (hashed, username))

            conn.commit()
            return "Password Reset Successful"

    return "Invalid OTP"

#--------------Work-load--------#

@app.route('/workload-data')
def workload_data():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT teacher, COUNT(*) FROM timetable GROUP BY teacher")
    data = cur.fetchall()

    conn.close()

    labels = [row[0] for row in data]
    values = [row[1] for row in data]

    return {"labels": labels, "values": values}


#-------------edit----------------#
@app.route('/edit/<int:id>')
def edit(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM timetable WHERE id=%s", (id,))
    row = cur.fetchone()

    conn.close()
    return render_template('edit.html', row=row)


@app.route('/update/<int:id>', methods=['POST'])
def update(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    UPDATE timetable
    SET class=%s, day=%s, period=%s, subject=%s, teacher=%s
    WHERE id=%s
    """, (
        request.form['class'],
        request.form['day'],
        request.form['period'],
        request.form['subject'],
        request.form['teacher'],
        id
    ))

    conn.commit()
    conn.close()

    flash("Updated successfully!", "success")
    return redirect('/timetable')

#----------delete entries----------#
@app.route('/delete/<int:id>')
def delete(id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM timetable WHERE id=%s", (id,))

    conn.commit()
    conn.close()

    flash("Entry deleted successfully!", "success")
    return redirect('/timetable')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)