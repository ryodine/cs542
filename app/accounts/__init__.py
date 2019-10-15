from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, make_response
from jinja2 import TemplateNotFound
from util import database
from app.accounts.session import current_user, current_user_roles, invalidate_token, CS542_TOKEN_COOKIE, CS542_TOKEN_COOKIE_EXPIRY, require_login, require_oneof_roles
import bcrypt
import hashlib
import secrets
import math

accounts = Blueprint('accounts', __name__,
                        template_folder='view')

#####################
# User Landing Page #
#####################

@accounts.route('/')
def show():
    try:
        user = current_user()
        if (user is not None):
            return render_template('user.html', user=user)
        else:
            return redirect(url_for('accounts.signin'))
    except TemplateNotFound:
        abort(500)

##############################
# Account Session Management #
##############################

@accounts.route('/login', methods=["GET","POST"])
def signin():
    if (request.method == "GET"):
        return render_template('login.html')
    elif (request.method == "POST"):
        db = database.get_db()
        with db.cursor() as cursor:
            studentIDHash = hashlib.sha512(request.form["studentID"].encode('utf-8')).hexdigest()
            get_user_login = "SELECT password_hash, userid, student_name FROM User WHERE student_id=%s;"
            cursor.execute(get_user_login, studentIDHash)
            result = cursor.fetchone()
            if (cursor.rowcount == 1 and bcrypt.checkpw(request.form["password"].encode('utf-8'), result['password_hash'].encode('utf-8'))):
                ## User successfuly authenticated, make the session for the user.

                # Delte any old session that exists
                delete_old_session_query = "DELETE FROM LoginSession WHERE userid=%s;"
                cursor.execute(delete_old_session_query, result['userid'])

                # Make a new session
                session_token = secrets.token_hex(30)
                make_user_session = "INSERT INTO LoginSession (userid, token) VALUES (%s, %s);"
                cursor.execute(make_user_session, (result['userid'], session_token))
                if (cursor.rowcount == 1):
                    db.commit()
                    resp = make_response(redirect('/' if "redirect" not in request.args else request.args["redirect"]))
                    resp.set_cookie(CS542_TOKEN_COOKIE, session_token)

                    flash('Welcome, %s.' % result['student_name'], 'success')
                    return resp
                else:
                    flash('Login Failed.', 'danger')
                    return render_template('login.html')
            else:
                flash('Login Failed.', 'danger')
                return render_template('login.html')
            return ""

@accounts.route('/logout', methods=["GET","POST"])
def signout():
    if (current_user() is not None):
        invalidate_token(current_user()['session_token'])
        resp = make_response(redirect('/'))
        resp.set_cookie(CS542_TOKEN_COOKIE, '', 0)
        flash('Logged Out', 'success')
        return resp
    else:
        abort(500)

@accounts.route('/new', methods=["GET","POST"])
def signup():
    if request.method == "POST":
        ## Post method, process data
        for _, v in request.form.items():
            if v is None or v.strip() == "":
                flash('Make sure that you fill in every field', 'danger')
                return redirect(url_for('accounts.signup', **request.args))

        if (request.form["password"] != request.form["confirmpassword"]):
            flash('Make sure that your passwords match', 'danger')
            return redirect(url_for('accounts.signup', **request.args))
        
        db = database.get_db()
        with db.cursor() as cursor:
            salt = bcrypt.gensalt()
            studentIDHash = hashlib.sha512(request.form["studentID"].encode('utf-8')).hexdigest()
            add_user_query = "INSERT INTO User (student_id, student_name, join_date, password_hash) VALUES " + \
                             "(%s, %s, CURDATE(), %s);"
            cursor.execute(add_user_query, (studentIDHash, request.form["name"], bcrypt.hashpw(request.form["password"].encode('utf-8'), salt)))
            if (cursor.rowcount == 1):
                db.commit()
                flash('Created user account', 'success')
                return redirect(url_for('accounts.signup', **request.args))
            else:
                flash('Error creating user. Does one already exist?', 'danger')
                return redirect(url_for('accounts.signup', **request.args))
    else:
        ## Get method, show the form
        try:
            # Pre-fill id if supplied.
            id = ''
            if ('id' in request.args.keys()):
                id = request.args["id"]
            return render_template('register.html', id=id)

        except TemplateNotFound:
            abort(500)

##########################
# Account Administration #
##########################

@accounts.route('/admin', methods=["GET","POST"])
@require_oneof_roles("admin", "opener")
def admin():
    # Page Limit
    LIMIT = 10

    db = database.get_db()
    if request.method == "GET":
        query_conditions = []
        for arg, val in request.args.items():
            if (arg == "paid"):
                query_conditions.append("paid=%s" % db.escape(val))
            elif (arg == "waiver"):
                query_conditions.append("waiver=%s" % db.escape(val))
            elif (arg == "cpr"):
                query_conditions.append("cpr_certified=%s" % db.escape(val))
            elif (arg == "name"):
                query_conditions.append("student_name LIKE %s" % db.escape("%" + val + "%"))
            elif (arg == "setter"):
                query_conditions.append("roles " + ("NOT " if val=="0" else "") + "LIKE '%setter%'")
            elif (arg == "opener"):
                query_conditions.append("roles " + ("NOT " if val=="0" else "") + "LIKE '%opener%'")
            elif (arg == "admin"):
                query_conditions.append("roles " + ("NOT " if val=="0" else "") + "LIKE '%admin%'")

        with db.cursor() as cursor:
            query = "SELECT COUNT(*) as ct FROM UserDataWithRole"
            if (len(query_conditions) > 0):
                query += " WHERE " + (" AND ".join(query_conditions))
            print(query)
            cursor.execute(query)
            count = cursor.fetchone()["ct"]
        # Pagination calculations
        page = int(request.args["page"]) if "page" in request.args else 0
        offset = page*LIMIT
        maxpage = math.ceil(count/LIMIT)-1
        print(page, count, maxpage, maxpage*LIMIT)
        pages = []
        if (maxpage >= 2):
            if (page == 0):
                pages.append(0)
                pages.append(1)
                pages.append(2)
            elif (page == maxpage):
                pages.append(maxpage-2)
                pages.append(maxpage-1)
                pages.append(maxpage)
            else:
                pages.append(page-1)
                pages.append(page)
                pages.append(page+1)
        elif (maxpage == 1):
            pages.append(0)
            pages.append(1)
        else:
            pages.append(0)

        with db.cursor() as cursor:
            query = "SELECT * FROM UserDataWithRole"
            if (len(query_conditions) > 0):
                query += " WHERE " + (" AND ".join(query_conditions))
            query += " LIMIT %s offset %s"
            print(query)
            cursor.execute(query, (LIMIT, offset))
            result = cursor.fetchall()

        return render_template('admin.html', userlist=result, pages=pages, page=page, maxpage=maxpage, limit=LIMIT, count=count, search_name = request.args["name"] if "name" in request.args else "")
    elif request.method == "POST":
        param = None
        val = None
        for attr in ["paid", "waiver", "cpr_certified"]:
            if attr in request.form:
                param = attr
                val = request.form[attr]
                break
        if not param == None:
            if ( 'admin' in current_user_roles() or ((param == "paid" or param == "waiver") and int(val) == 1)):
                with db.cursor() as cursor:
                    userupdate = "UPDATE UserData SET " + param + "=%s WHERE userid=%s"
                    cursor.execute(userupdate, (val, request.form["userid"]))
                    db.commit()
                return redirect(url_for('accounts.admin', **request.args))
            else:
                abort(403)
        
        if ( 'admin' in current_user_roles() ):
            for attr in ["setter", "opener", "admin"]:
                if attr in request.form:
                    param = attr
                    val = request.form[attr]
                    break
            if (current_user()["userid"] == int(request.form["userid"]) and param == "admin" and int(val) == 0):
                flash("You cannot demote yourself", "danger")
                return redirect(url_for('accounts.admin', **request.args))
            if not param == None:
                with db.cursor() as cursor:
                    userupdate = None
                    if (int(val) == 1):
                        userupdate = "INSERT INTO UserRoles VALUES(%s,%s)"
                    else:
                        userupdate = "DELETE FROM UserRoles WHERE userid=%s AND role=%s"
                    cursor.execute(userupdate, (request.form["userid"], param))
                    db.commit()
                return redirect(url_for('accounts.admin', **request.args))

            if ("delete" in request.form):
                with db.cursor() as cursor:
                    userdel = "DELETE FROM User WHERE userid=%s"
                    cursor.execute(userdel, (request.form["delete"]))
                db.commit()
                return redirect(url_for('accounts.admin', **request.args))

            abort(400)
        else:
            abort(403)

@accounts.route('/edit/<id>', methods=["GET","POST"])
@require_login
def edit(id):
    current_u = current_user()
    if ((current_u["userid"] != id and 'admin' not in current_user_roles())):
        abort(403)
    db = database.get_db()
    if (request.method == "GET"):
        with db.cursor() as cursor:
            usersel = "SELECT * FROM UserDataWithRole WHERE userid=%s"
            cursor.execute(usersel, id)
            return render_template('edit.html', user=cursor.fetchone())
    elif (request.method == "POST"):
        if ("delete" in request.form):
            with db.cursor() as cursor:
                userdel = "DELETE FROM User WHERE userid=%s"
                cursor.execute(userdel, (id))
            db.commit()
            if ("admin" in current_user_roles()):
                return redirect(url_for('accounts.admin', **request.args))
            else:
                return redirect(url_for('/', **request.args))
        elif ("password" in request.form and "oldpassword" in request.form and "confirmpassword" in request.form):
            if (request.form["password"] == "" or request.form["confirmpassword"] == "" or request.form["confirmpassword"] != request.form["password"]):
                flash("Please provide a new password, and make sure you've entered the same password twice", "danger")
                return redirect(url_for('accounts.edit', id=id, **request.args))
            with db.cursor() as cursor:
                usersel = "SELECT password_hash FROM User WHERE userid=%s"
                cursor.execute(usersel, id)

                # Admins can change other user's passwords, or the user when providing the right password can change other user's passwords
                if (("admin" in current_user_roles() and current_u["userid"] != int(id)) or bcrypt.checkpw(request.form["oldpassword"].encode('utf-8'), cursor.fetchone()['password_hash'].encode('utf-8'))):
                    with db.cursor() as cursor:
                        changepw = "UPDATE User SET password_hash=%s WHERE userid=%s"
                        cursor.execute(changepw, (bcrypt.hashpw(request.form["password"].encode('utf-8'), bcrypt.gensalt()), id))
                    db.commit()
                    if "admin" in current_user_roles() and current_u["userid"] != int(id):
                        flash("Password Changed Successfully", "success")
                    else:
                        flash("Password Changed Successfully. Please sign in with your new password.", "success")
                    return redirect(url_for('accounts.edit', id=id, **request.args))
                else:
                   flash("Incorrect Password or Unauthorized", "danger")
                   return redirect(url_for('accounts.edit', id=id, **request.args))
        elif ("name" in request.form):
            with db.cursor() as cursor:
                userdel = "UPDATE UserData set student_name=%s WHERE userid=%s"
                cursor.execute(userdel, (request.form["name"], id))
            db.commit()
            flash("Name changed successfully", "success")
            return redirect(url_for('accounts.edit', id=id, **request.args))
        else:
            abort(400)
