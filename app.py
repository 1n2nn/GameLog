from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
import uuid

from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key =  os.environ.get(
    "SECRET_KEY",
    "development-secret-key"
)

UPLOAD_FOLDER = "static/uploads"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE = "games.db"


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()

    # ユーザーテーブル
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    # ゲームテーブル
    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            genre TEXT,
            status TEXT,
            play_time INTEGER,
            rating INTEGER,
            review TEXT,
            image TEXT
        )
    """)

    # gamesテーブルにuser_idが存在するか確認
    columns = conn.execute(
        "PRAGMA table_info(games)"
    ).fetchall()

    column_names = [column["name"] for column in columns]

    # user_idがまだ存在しない場合だけ追加
    if "user_id" not in column_names:

        conn.execute(
            "ALTER TABLE games ADD COLUMN user_id INTEGER"
        )

    conn.commit()
    conn.close()


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # ユーザー名チェック
        if not username:
            return "ユーザー名を入力してください", 400

        if len(username) > 30:
            return "ユーザー名は30文字以内で入力してください", 400

        # パスワードチェック
        if not password:
            return "パスワードを入力してください", 400

        if len(password) < 6:
            return "パスワードは6文字以上で入力してください", 400

        if len(password) > 100:
            return "パスワードは100文字以内で入力してください", 400

        conn = get_db_connection()

        # 同じユーザー名が存在するか確認
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if existing_user:
            conn.close()
            return "このユーザー名はすでに使用されています", 400

        # パスワードをハッシュ化
        hashed_password = generate_password_hash(password)

        # ユーザーを登録
        cursor = conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed_password)
        )
        
        conn.commit()
        
        user_id = cursor.lastrowid
        
        conn.close()
        
        # 登録したユーザーで自動ログイン
        session["user_id"] = user_id
        session["username"] = username
        
        return redirect("/")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return "ユーザー名とパスワードを入力してください", 400

        conn = get_db_connection()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        conn.close()

        # ユーザーが存在しない場合
        if user is None:
            return "ユーザー名またはパスワードが正しくありません", 400

        # パスワードを確認
        if not check_password_hash(user["password"], password):
            return "ユーザー名またはパスワードが正しくありません", 400

        # ログイン情報をセッションに保存
        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():

    # セッションからログイン情報を削除
    session.pop("user_id", None)
    session.pop("username", None)

    return redirect("/login")


@app.route("/")
def index():

    # ログインしているユーザーを確認
    user_id = session.get("user_id")

    # 未ログインの場合
    if user_id is None:
        return redirect("/login")

    keyword = request.args.get("keyword", "").strip()
    genre = request.args.get("genre", "").strip()
    status = request.args.get("status", "").strip()

    conn = get_db_connection()

    # ゲーム検索
    query = "SELECT * FROM games WHERE user_id = ?"
    params = [user_id]

    if keyword:
        query += " AND title LIKE ?"
        params.append(f"%{keyword}%")

    if genre:
        query += " AND genre = ?"
        params.append(genre)

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id DESC"

    games = conn.execute(
        query,
        params
    ).fetchall()

    # 統計情報
    total_games = conn.execute(
        """
        SELECT COUNT(*)
        FROM games
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]
    
    completed_games = conn.execute(
        """
        SELECT COUNT(*)
        FROM games
        WHERE status = ?
          AND user_id = ?
        """,
        ("クリア済み", user_id)
    ).fetchone()[0]
    
    playing_games = conn.execute(
        """
        SELECT COUNT(*)
        FROM games
        WHERE status = ?
          AND user_id = ?
        """,
        ("プレイ中", user_id)
    ).fetchone()[0]
    
    total_play_time = conn.execute(
        """
        SELECT COALESCE(SUM(play_time), 0)
        FROM games
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]
    
    # ジャンル別ゲーム数
    genre_stats = conn.execute(
        """
        SELECT genre, COUNT(*) AS count
        FROM games
        WHERE user_id = ?
          AND genre IS NOT NULL
          AND genre != ''
        GROUP BY genre
        ORDER BY count DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "index.html",
        games=games,
        keyword=keyword,
        selected_genre=genre,
        selected_status=status,
        total_games=total_games,
        completed_games=completed_games,
        playing_games=playing_games,
        total_play_time=total_play_time,
        genre_stats=genre_stats
    )


@app.route("/add", methods=["GET", "POST"])
def add_game():

    # ログインしているユーザーを確認
    user_id = session.get("user_id")

    if user_id is None:
        return redirect("/login")

    if request.method == "POST":

        # 入力値を取得
        title = request.form.get("title", "").strip()
        genre = request.form.get("genre", "").strip()
        status = request.form.get("status", "").strip()
        play_time_text = request.form.get("play_time", "").strip()
        rating_text = request.form.get("rating", "").strip()
        review = request.form.get("review", "").strip()

        # -------------------------
        # 入力チェック
        # -------------------------

        # タイトル
        if not title:
            return "ゲームタイトルを入力してください", 400

        # ジャンル
        allowed_genres = [
            "",
            "アクション",
            "RPG",
            "アドベンチャー",
            "シミュレーション",
            "パズル",
            "スポーツ",
            "サンドボックス",
            "その他"
        ]

        if genre not in allowed_genres:
            return "正しいジャンルを選択してください", 400

        # プレイ状況
        allowed_statuses = [
            "",
            "プレイ予定",
            "プレイ中",
            "クリア済み",
            "積みゲー"
        ]

        if status not in allowed_statuses:
            return "正しいプレイ状況を選択してください", 400

        # プレイ時間
        play_time = None

        if play_time_text:
            try:
                play_time = int(play_time_text)
            except ValueError:
                return "プレイ時間は整数で入力してください", 400

            if play_time < 0:
                return "プレイ時間は0以上で入力してください", 400

            if play_time > 100000:
                return "プレイ時間が大きすぎます", 400

        # 評価
        rating = None

        if rating_text:
            try:
                rating = int(rating_text)
            except ValueError:
                return "評価の値が正しくありません", 400

            if rating < 1 or rating > 5:
                return "評価は1～5の範囲で入力してください", 400


        # -------------------------
        # 画像処理
        # -------------------------

        image = request.files.get("image")

        filename = None

        if image and image.filename:

            extension = os.path.splitext(image.filename)[1].lower()

            allowed_extensions = [
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".webp"
            ]

            if extension not in allowed_extensions:
                return "対応していない画像形式です", 400

            filename = f"{uuid.uuid4()}{extension}"

            image.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )
            )


        # -------------------------
        # データベースへ登録
        # -------------------------

        conn = get_db_connection()

        conn.execute(
            """
            INSERT INTO games
            (title, genre, status, play_time, rating, review, image, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                genre,
                status,
                play_time,
                rating,
                review,
                filename,
                user_id
            )
        )
        conn.commit()
        conn.close()

        return redirect("/")

    return render_template("add.html")


@app.route("/game/<int:game_id>")
def game_detail(game_id):

    # ログインしているユーザーを確認
    user_id = session.get("user_id")

    if user_id is None:
        return redirect("/login")

    conn = get_db_connection()

    # 自分が登録したゲームだけ取得
    game = conn.execute(
        """
        SELECT *
        FROM games
        WHERE id = ?
          AND user_id = ?
        """,
        (game_id, user_id)
    ).fetchone()

    conn.close()

    if game is None:
        return "ゲームが見つかりません", 404

    return render_template(
        "detail.html",
        game=game
    )


@app.route("/game/<int:game_id>/edit", methods=["GET", "POST"])
def edit_game(game_id):

    # ログインしているユーザーを確認
    user_id = session.get("user_id")

    if user_id is None:
        return redirect("/login")

    conn = get_db_connection()

    # 自分が登録したゲームだけ取得
    game = conn.execute(
        """
        SELECT *
        FROM games
        WHERE id = ?
          AND user_id = ?
        """,
        (game_id, user_id)
    ).fetchone()

    if game is None:
        conn.close()
        return "ゲームが見つかりません", 404

    if request.method == "POST":

        title = request.form["title"].strip()
        genre = request.form["genre"]
        status = request.form["status"]
        play_time = request.form["play_time"]
        rating = request.form["rating"]
        review = request.form["review"].strip()
    
        # タイトルチェック
        if not title:
            return "タイトルを入力してください", 400
    
        # プレイ時間チェック
        try:
            play_time = int(play_time)
    
            if play_time < 0:
                return "プレイ時間は0以上で入力してください", 400
    
        except ValueError:
            return "プレイ時間は整数で入力してください", 400
    
        # 評価チェック
        try:
            rating = int(rating)
    
            if rating < 1 or rating > 5:
                return "評価は1～5で入力してください", 400
    
        except ValueError:
            return "評価は整数で入力してください", 400
    
        image = request.files.get("image")
    
        filename = game["image"]

        if image and image.filename:

            extension = os.path.splitext(
                image.filename
            )[1].lower()
        
            allowed_extensions = {
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".webp"
            }
        
            if extension not in allowed_extensions:
                return "対応していない画像形式です", 400
        
            new_filename = f"{uuid.uuid4()}{extension}"

            image.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    new_filename
                )
            )

            # 古い画像を削除
            if game["image"]:

                old_image_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    game["image"]
                )

                if os.path.exists(old_image_path):
                    os.remove(old_image_path)

            filename = new_filename

        conn.execute(
            """
            UPDATE games
            SET title = ?,
                genre = ?,
                status = ?,
                play_time = ?,
                rating = ?,
                review = ?,
                image = ?
            WHERE id = ?
              AND user_id = ?
            """,
            (
                title,
                genre,
                status,
                play_time,
                rating,
                review,
                filename,
                game_id,
                user_id
            )
        )

        conn.commit()
        conn.close()

        return redirect(f"/game/{game_id}")

    conn.close()

    return render_template(
        "edit.html",
        game=game
    )


@app.route("/game/<int:game_id>/delete", methods=["POST"])
def delete_game(game_id):

    # ログインしているユーザーを確認
    user_id = session.get("user_id")

    if user_id is None:
        return redirect("/login")

    conn = get_db_connection()

    # 自分が登録したゲームだけ取得
    game = conn.execute(
        """
        SELECT *
        FROM games
        WHERE id = ?
          AND user_id = ?
        """,
        (game_id, user_id)
    ).fetchone()

    # ゲームが存在しない、または他ユーザーのゲームの場合
    if game is None:
        conn.close()
        return "ゲームが見つかりません", 404

    # 画像ファイル名を保存
    image_filename = game["image"]

    # データベースから削除
    conn.execute(
        """
        DELETE FROM games
        WHERE id = ?
          AND user_id = ?
        """,
        (game_id, user_id)
    )

    conn.commit()
    conn.close()

    # 関連する画像ファイルを削除
    if image_filename:

        image_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            image_filename
        )

        if os.path.exists(image_path):
            os.remove(image_path)

    return redirect("/")


init_db()

if __name__ == "__main__":
    app.run(debug=False)