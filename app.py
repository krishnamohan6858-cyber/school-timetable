from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import smtplib
import random
import os
import bcrypt
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret")

# ---------------- DATABASE ----------------


def get_db_connection():
    DATABASE_URL = os.environ.get("DATABASE_URL")

    if DATABASE_URL:
        # For Render (production)
        return psycopg2.connect(DATABASE_URL)
    else:
        # For Local (your PC)
        return psycopg2.connect(
            host="localhost",
            database="school_timetable",
            user="postgres",
            password="Triplet@5714"  # 👈 put your real password
        )

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

def get_daily_load(day):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT teacher, COUNT(*) FROM timetable
    WHERE day=%s GROUP BY teacher
    """, (day,))

    data = cur.fetchall()
    conn.close()
    return dict(data)


def get_weekly_load():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT teacher, COUNT(*) FROM timetable
    GROUP BY teacher
    """)

    data = cur.fetchall()
    conn.close()
    return dict(data)


def get_substitution_count(day):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT substitute, COUNT(*) FROM timetable
    WHERE day=%s AND substitute IS NOT NULL AND substitute != ''
    GROUP BY substitute
    """, (day,))

    data = cur.fetchall()
    conn.close()
    return dict(data)


def get_busy_teachers(day, period):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT teacher FROM timetable
    WHERE day=%s AND period=%s
    """, (day, period))

    busy = [t[0] for t in cur.fetchall()]
    conn.close()
    return busy


def reset_daily_substitutions():
    conn = get_db_connection()
    cur = conn.cursor()

    today = date.today()

    # Reset anything not from today (i.e., yesterday or older)
    cur.execute("""
        UPDATE timetable
        SET substitute = NULL, substitute_date = NULL
        WHERE substitute_date IS NOT NULL
        AND substitute_date < %s
    """, (today,))

    conn.commit()
    conn.close()


@app.route('/')
def home():
    if 'admin' not in session:
        return redirect('/login')   # Teachers go to login

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT name FROM teachers")
    teachers = [t[0] for t in cur.fetchall()]

    conn.close()
    return render_template('index.html', teachers=teachers)


def get_substitute(day, period):
    conn = get_db_connection()
    cur = conn.cursor()

    # Get all teachers
    cur.execute("SELECT name FROM teachers")
    all_teachers = [t[0] for t in cur.fetchall()]
    conn.close()

    busy_teachers = get_busy_teachers(day, period)
    daily_load = get_daily_load(day)
    weekly_load = get_weekly_load()
    subs_count = get_substitution_count(day)

    # Step 1: Only free teachers
    free_teachers = [t for t in all_teachers if t not in busy_teachers]

    # Step 2: Remove overloaded teachers (>40 weekly)
    free_teachers = [t for t in free_teachers if weekly_load.get(t, 0) <= 40]

    def pick_teacher(max_periods, max_subs):
        candidates = []

        for t in free_teachers:
            day_load = daily_load.get(t, 0)
            subs = subs_count.get(t, 0)
            total = weekly_load.get(t, 0)

            if day_load <= max_periods and subs < max_subs:
                candidates.append((t, total))

        # Sort by least workload
        candidates.sort(key=lambda x: x[1])

        return candidates[0][0] if candidates else None

    # ---------------- PRIORITY SYSTEM ---------------- #

    # 🥇 PRIORITY 1
    # Teachers with <=6 periods, no substitution yet
    teacher = pick_teacher(max_periods=6, max_subs=1)
    if teacher:
        return teacher

    # 🥈 PRIORITY 2
    # Teachers with <=7 periods, max 1 substitution
    teacher = pick_teacher(max_periods=7, max_subs=1)
    if teacher:
        return teacher

    # 🥉 PRIORITY 3
    # Teachers with <=6 periods, allow second substitution
    teacher = pick_teacher(max_periods=6, max_subs=2)
    if teacher:
        return teacher

    # 🟡 PRIORITY 4 (LAST OPTION)
    # Teachers with <=8 periods, max 2 substitutions
    teacher = pick_teacher(max_periods=8, max_subs=1)
    if teacher:
        return teacher

    return "No substitute available"




# # ---------------- ROUTES ----------------


@app.route('/timetable')
def timetable():

    # 🔥 AUTO RESET (midnight logic)
    reset_daily_substitutions()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM timetable")
    data = cur.fetchall()

    # Convert to grid format
    grid = {}
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    for d in days:
        grid[d] = {}

    for row in data:
        # 👇 UPDATED unpacking (added substitute_date)
        id, class_name, day, period, subject, teacher, substitute, substitute_date = row

        grid[day][period] = {
            "id": id,
            "class": class_name,
            "subject": subject,
            "teacher": teacher,
            "substitute": substitute,
            "substitute_date": substitute_date   # 🔥 IMPORTANT
        }

    # Get teachers list (for dropdown)
    cur.execute("SELECT name FROM teachers")
    teachers = [t[0] for t in cur.fetchall()]

    conn.close()

    return render_template(
        'timetable_grid.html',
        grid=grid,
        days=days,
        periods=range(1, 11),
        teachers=teachers
    )



@app.route('/update-substitute/<int:id>', methods=['POST'])
def update_substitute(id):
    if 'admin' not in session:
        return redirect('/admin-login')

    substitute = request.form['substitute']
    today = date.today()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE timetable
        SET substitute=%s, substitute_date=%s
        WHERE id=%s
    """, (substitute, today, id))

    conn.commit()
    conn.close()

    flash("✅ Substitute updated!", "success")
    return redirect('/timetable')



@app.route('/add', methods=['POST'])
def add():
    if 'admin' not in session:
        return redirect('/admin-login')   # 🔒 Restrict

    class_name = request.form['class'].strip()
    day = request.form['day']
    period = request.form['period']
    subject = request.form['subject']
    teacher = request.form['teacher']

    conn = get_db_connection()
    cur = conn.cursor()

    # Check class conflict
    cur.execute("""
    SELECT * FROM timetable
    WHERE class=%s AND day=%s AND period=%s
    """, (class_name, day, period))

    if cur.fetchone():
        conn.close()
        flash("⚠️ Class already assigned!", "error")
        return redirect('/')

    # Check teacher conflict
    cur.execute("""
    SELECT * FROM timetable
    WHERE teacher=%s AND day=%s AND period=%s
    """, (teacher, day, period))

    if cur.fetchone():
        conn.close()
        flash("⚠️ Teacher already busy!", "error")
        return redirect('/')

    cur.execute("""
    INSERT INTO timetable (class, day, period, subject, teacher, substitute)
    VALUES (%s, %s, %s, %s, %s, %s)
    """, (class_name, day, period, subject, teacher, ""))

    conn.commit()
    conn.close()

    flash("✅ Entry added!", "success")
    return redirect('/')


@app.route('/absent', methods=['POST'])
def mark_absent():
    day = request.form['day']
    period = int(request.form['period'])
    teacher = request.form['teacher']

    substitute = get_substitute(day, period)

    conn = get_db_connection()
    cur = conn.cursor()

    today = date.today()

    cur.execute("""
    UPDATE timetable
    SET substitute=%s, substitute_date=%s
    WHERE day=%s AND period=%s AND teacher=%s
    """, (substitute, today, day, period, teacher))

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

    rows = cur.fetchall()
    conn.close()

    # 🧠 Convert into GRID format
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    periods = list(range(1, 11))

    grid = {p: {d: None for d in days} for p in periods}

    for row in rows:
        day, period, subject, cls, sub = row
        grid[period][day] = {
            "subject": subject,
            "class": cls,
            "substitute": sub
        }

    return render_template('teacher.html',
                           teacher=name,
                           grid=grid,
                           days=days,
                           periods=periods)



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

        if data:
            stored_password = data[0]

            # ✅ HANDLE BOTH CASES (OLD + NEW)
            if stored_password.startswith("$2b$"):
                # 🔒 Hashed password
                if bcrypt.checkpw(password.encode(), stored_password.encode()):
                    session['admin'] = username
                    return redirect('/admin-dashboard')
                else:
                    flash("❌ Invalid username or password", "error")
            else:
                # ⚠️ Plain password (old DB)
                if password == stored_password:
                    session['admin'] = username
                    return redirect('/admin-dashboard')
                else:
                    flash("❌ Invalid username or password", "error")
        else:
            flash("❌ Invalid username or password", "error")

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


@app.route('/change-admin-password', methods=['GET', 'POST'])
def change_admin_password():
    if 'admin' not in session:
        return redirect('/admin-login')

    conn = get_db_connection()
    cur = conn.cursor()

    msg = None

    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        cur.execute("SELECT password FROM admin WHERE username=%s", (session['admin'],))
        data = cur.fetchone()

        if data:
            stored_password = data[0]

            # ✅ Handle hashed password
            if stored_password.startswith("$2b$"):
                if bcrypt.checkpw(old_password.encode(), stored_password.encode()):
                    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
                    cur.execute("UPDATE admin SET password=%s WHERE username=%s",
                                (hashed, session['admin']))
                    conn.commit()
                    flash("✅ Password updated successfully!", "success")
                else:
                    flash("❌ Wrong old password", "error")

            # ⚠️ Handle old plain password
            else:
                if old_password == stored_password:
                    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
                    cur.execute("UPDATE admin SET password=%s WHERE username=%s",
                                (hashed, session['admin']))
                    conn.commit()
                    flash("✅ Password updated successfully!", "success")
                else:
                    flash("❌ Wrong old password", "error")

    conn.close()
    return render_template('change_password.html', msg=msg)


# ---------------- OTP RESET ----------------


@app.route('/forgot-password', methods=['GET'])
def forgot_password():
    return render_template('forgot_password.html')

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

        flash("✅ OTP sent to your email", "success")
        return render_template('verify_otp.html', username=username)

    flash("❌ Username not found", "error")
    return redirect('/forgot-password')


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



@app.route('/edit/<int:id>')
def edit(id):
    if 'admin' not in session:
        return redirect('/admin-login')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM timetable WHERE id=%s", (id,))
    row = cur.fetchone()

    conn.close()
    return render_template('edit.html', row=row)




@app.route('/update/<int:id>', methods=['POST'])
def update(id):
    if 'admin' not in session:
        return redirect('/admin-login')

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



@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    if 'admin' not in session:
        return redirect('/admin-login')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM timetable WHERE id=%s", (id,))

    conn.commit()
    conn.close()

    return '', 204


from flask import jsonify

@app.route('/inline-update/<int:id>', methods=['POST'])
def inline_update(id):
    if 'admin' not in session:
        return jsonify({"status": "error"})

    data = request.get_json()

    subject = data.get('subject')
    class_name = data.get('class_name')
    teacher = data.get('teacher')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE timetable
        SET subject=%s, class=%s, teacher=%s
        WHERE id=%s
    """, (subject, class_name, teacher, id))

    conn.commit()
    conn.close()

    return jsonify({"status": "success"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)