"""
FC온라인 선수 카드 웹 애플리케이션
Flask + PostgreSQL
"""

import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import hashlib
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_dance.contrib.google import make_google_blueprint, google
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fconq-super-secret-key-change-later-12345')  # ⚠️ 나중에 변경 필요

# ✅ 로그인 매니저 초기화
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # 로그인 필요 시 리디렉션할 페이지

# DB 연결 설정
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "database": os.environ.get("DB_NAME", "fconline"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "9787")
}

# IP 해싱 함수
def hash_ip(ip_address):
    """IP 주소를 해시 처리 (개인정보 보호)"""
    secret = "fconline_secret_key_2025"  # 비밀키 (변경 가능)
    return hashlib.sha256(f"{ip_address}{secret}".encode()).hexdigest()

# 시즌 정렬 순서 (공식 홈페이지 기준)
SEASON_ORDER = [
    100, 110, 101, 113, 114, 111, 848, 850, 846, 845, 849, 840,
    839, 836, 829, 828, 827, 826, 825, 821, 815, 818,
    814, 813, 802, 801, 290, 291, 289, 283, 284, 272,
    273, 274, 270, 268, 265, 264, 835, 811, 281, 261,
    256, 252, 251, 253, 249, 246, 237, 231, 233, 254,
    236, 804, 276, 262, 238, 219, 218, 217, 216, 214,
    213, 210, 207, 206, 202, 201, 831, 832, 807, 808,
    278, 279, 258, 259, 240, 241, 220, 222, 211, 212,
    844, 820, 287, 267, 250, 230, 215, 834, 810, 280,
    260, 242, 221, 234, 225, 806, 293, 294, 295, 298,
    297, 247, 516, 514, 512, 510, 507, 504, 830, 805,
    277, 257, 239, 515, 513, 511, 508, 506, 503, 502,
    501, 500, 300, 323, 322, 321, 320, 319, 318, 317,
    812
]

# ✅ User 클래스
class User(UserMixin):
    def __init__(self, id, email, name, profile_image=None):
        self.id = id
        self.email = email
        self.name = name
        self.profile_image = profile_image

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user_data = cur.fetchone()
    cur.close()
    conn.close()
    
    if user_data:
        return User(user_data['id'], user_data['email'], user_data['name'], user_data.get('profile_image'))
    return None


# ✅ 구글 OAuth 블루프린트
google_bp = make_google_blueprint(
    client_id=os.environ.get("GOOGLE_CLIENT_ID", "581851547657-gbtk81a83k7nr188p347ardjciufkudd.apps.googleusercontent.com"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "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"),
    redirect_to="google_authorized",
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]
)
app.register_blueprint(google_bp, url_prefix="/login")


def get_db_connection():
    """DB 연결 생성"""
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    return conn


@app.route('/')
def index():
    """메인 페이지 = 검색 페이지"""
    # search() 함수 그대로 실행
    return search()

@app.route('/community')
def community_list():
    """커뮤니티 메인 - 게시글 목록"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 파라미터
    category = request.args.get('category', '')
    page = request.args.get('page', 1, type=int)
    search_type = request.args.get('search_type', '')
    keyword = request.args.get('keyword', '')
    show_popular = request.args.get('popular', '') == 'true'
    per_page = 20
    
    # 기본 쿼리
    query = "SELECT * FROM community.posts"
    params = []
    conditions = []
    
    # 카테고리 필터
    if category:
        conditions.append("category = %s")
        params.append(category)
        
    # 인기글 필터 추가
    if show_popular:
        conditions.append("is_popular = true")    
    
    # 검색 조건
    if keyword and search_type:
        # 검색어를 공백으로 분리
        keywords = keyword.split()
        
        if search_type == 'title':
            # 제목 검색
            search_conditions = []
            for kw in keywords:
                # 띄어쓰기 무시: 검색어와 DB 데이터 모두 공백 제거
                search_conditions.append("REPLACE(title, ' ', '') ILIKE %s")
                params.append(f'%{kw.replace(" ", "")}%')
            conditions.append(f"({' AND '.join(search_conditions)})")
            
        elif search_type == 'content':
            # 내용 검색
            search_conditions = []
            for kw in keywords:
                search_conditions.append("REPLACE(content, ' ', '') ILIKE %s")
                params.append(f'%{kw.replace(" ", "")}%')
            conditions.append(f"({' AND '.join(search_conditions)})")
            
        elif search_type == 'title_content':
            # 제목+내용 검색
            search_conditions = []
            for kw in keywords:
                search_conditions.append("(REPLACE(title, ' ', '') ILIKE %s OR REPLACE(content, ' ', '') ILIKE %s)")
                kw_no_space = kw.replace(" ", "")
                params.extend([f'%{kw_no_space}%', f'%{kw_no_space}%'])
            conditions.append(f"({' AND '.join(search_conditions)})")
            
        elif search_type == 'author':
            # 글쓴이 검색
            search_conditions = []
            for kw in keywords:
                search_conditions.append("REPLACE(author, ' ', '') ILIKE %s")
                params.append(f'%{kw.replace(" ", "")}%')
            conditions.append(f"({' AND '.join(search_conditions)})")
            
        elif search_type == 'comment':
            # 댓글 검색
            search_conditions = []
            for kw in keywords:
                search_conditions.append("""
                    id IN (
                        SELECT post_id FROM community.comments 
                        WHERE REPLACE(content, ' ', '') ILIKE %s
                    )
                """)
                params.append(f'%{kw.replace(" ", "")}%')
            conditions.append(f"({' AND '.join(search_conditions)})")
    
    # 조건 적용
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    # 전체 글 수 계산
    count_query = f"SELECT COUNT(*) FROM community.posts"
    if conditions:
        count_query += " WHERE " + " AND ".join(conditions)
    
    cur.execute(count_query, params.copy())
    total_count = cur.fetchone()['count']
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    # 페이징 적용
    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([per_page, (page - 1) * per_page])
    
    cur.execute(query, params)
    posts = cur.fetchall()
    
    # 날짜 포맷 처리 + 이미지/영상 감지
    from datetime import datetime, date
    today = date.today()
    
    for post in posts:
        post_date = post['created_at'].date()
        if post_date == today:
            post['display_date'] = post['created_at'].strftime('%H:%M')
        else:
            post['display_date'] = post['created_at'].strftime('%m-%d')
        
        post['has_image'] = '<img' in post['content']
        post['has_video'] = '<iframe' in post['content'] or 'youtube.com' in post['content'] or 'youtu.be' in post['content']
    
    cur.close()
    conn.close()
    
    return render_template('community.html', 
                         posts=posts,
                         current_page=page,
                         total_pages=total_pages,
                         category=category,
                         search_type=search_type,
                         keyword=keyword,
                         show_popular=show_popular)


@app.route('/community/write', methods=['GET', 'POST'])
def community_write():
    """글쓰기"""
    if request.method == 'POST':
        category = request.form.get('category')
        title = request.form.get('title')
        content = request.form.get('content')
        author = request.form.get('author', '익명')
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO community.posts (category, title, content, author)
            VALUES (%s, %s, %s, %s)
        """, (category, title, content, author))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return redirect('/community')
    
    return render_template('community_write.html')


@app.route('/community/post/<int:post_id>')
def community_post(post_id):
    """게시글 상세보기"""
    from flask import request
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 조회수 증가
    cur.execute("UPDATE community.posts SET views = views + 1 WHERE id = %s", (post_id,))
    conn.commit()
    
    # 게시글 조회
    cur.execute("SELECT * FROM community.posts WHERE id = %s", (post_id,))
    post = cur.fetchone()
    
    if not post:
        cur.close()
        conn.close()
        return "게시글을 찾을 수 없습니다", 404
    
    # 댓글 조회
    cur.execute("""
        SELECT * FROM community.comments 
        WHERE post_id = %s 
        ORDER BY created_at ASC
    """, (post_id,))
    comments = cur.fetchall()
    
    # URL에서 카테고리 파라미터 가져오기
    category_filter = request.args.get('category', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # 카테고리에 따라 게시글 목록 조회
    if category_filter:
        # 전체 개수
        cur.execute("""
            SELECT COUNT(*) FROM community.posts
            WHERE category = %s
        """, (category_filter,))
        total_count = cur.fetchone()['count']
        
        # 특정 카테고리만
        cur.execute("""
            SELECT id, category, title, author, created_at, views, likes, content
            FROM community.posts
            WHERE category = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (category_filter, per_page, (page - 1) * per_page))
    else:
        # 전체 개수
        cur.execute("SELECT COUNT(*) FROM community.posts")
        total_count = cur.fetchone()['count']
        
        # 전체 게시글
        cur.execute("""
            SELECT id, category, title, author, created_at, views, likes, content
            FROM community.posts
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, (page - 1) * per_page))
    
    related_posts = cur.fetchall()
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    # 날짜 포맷 처리
    from datetime import date
    today = date.today()
    for p in related_posts:
        post_date = p['created_at'].date()
        if post_date == today:
            p['display_date'] = p['created_at'].strftime('%H:%M')
        else:
            p['display_date'] = p['created_at'].strftime('%m-%d')
            
        # 이미지/영상 감지 추가
        p['has_image'] = '<img' in p['content']
        p['has_video'] = '<iframe' in p['content'] or 'youtube.com' in p['content'] or 'youtu.be' in p['content']    
    
    cur.close()
    conn.close()
    
    return render_template('community_post.html', 
                         post=post, 
                         comments=comments,
                         related_posts=related_posts,
                         current_category=category_filter,
                         current_page=page,
                         total_pages=total_pages)


@app.route('/community/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    """댓글 작성"""
    content = request.form.get('content')
    author = request.form.get('author', '익명')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO community.comments (post_id, content, author)
        VALUES (%s, %s, %s)
    """, (post_id, content, author))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(f'/community/post/{post_id}')


@app.route('/search') 
def search():
    """1페이지: 검색 페이지"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 모든 시즌 가져오기
    cur.execute("""
        SELECT season_id, season_name, season_img_url 
        FROM seasons
    """)
    all_seasons = cur.fetchall()
    
    # 시즌 ID를 키로 하는 딕셔너리 생성
    seasons_dict = {s['season_id']: s for s in all_seasons}
    
    # SEASON_ORDER 순서대로 정렬
    ordered_seasons = []
    for sid in SEASON_ORDER:
        if sid in seasons_dict:
            ordered_seasons.append(seasons_dict[sid])
    
    # 포지션 목록
    cur.execute("SELECT DISTINCT position FROM player_cards ORDER BY position")
    positions = [row['position'] for row in cur.fetchall()]
    
    # 국적 목록 (기존 코드 - 이제 사용 안 함)
    cur.execute("""
        SELECT DISTINCT full_data->'basic_info'->>'nation' as nation 
        FROM player_cards 
        WHERE full_data->'basic_info'->>'nation' IS NOT NULL
        ORDER BY nation
    """)
    nations_old = [row['nation'] for row in cur.fetchall() if row['nation'] and row['nation'] != 'Unknown']
    
    # 팀컬러 데이터 가져오기
    # 1. 국가 팀컬러
    cur.execute("SELECT nation_name FROM nation_teamcolors ORDER BY nation_name")
    nation_teamcolors = [row['nation_name'] for row in cur.fetchall()]
    
    # 2. 소속 팀컬러
    cur.execute("SELECT club_name FROM club_teamcolors ORDER BY club_name")
    club_teamcolors = [row['club_name'] for row in cur.fetchall()]
    
    # 3. 특성 팀컬러
    cur.execute("SELECT trait_name FROM trait_teamcolors ORDER BY trait_name")
    trait_teamcolors = [row['trait_name'] for row in cur.fetchall()]
    
    # 4. 고유 특성 데이터 가져오기
    # 신규 특성
    cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new' ORDER BY trait_name")
    new_traits = [row['trait_name'] for row in cur.fetchall()]
    
    # 일반 특성
    cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'normal' ORDER BY trait_name")
    normal_traits = [row['trait_name'] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return render_template('search.html', 
                         seasons=ordered_seasons,
                         positions=positions,
                         nations=nations_old,  # 기존 호환성 유지
                         nation_teamcolors=nation_teamcolors,
                         club_teamcolors=club_teamcolors,
                         trait_teamcolors=trait_teamcolors,
                         new_traits=new_traits,
                         normal_traits=normal_traits)

@app.route('/results')
def results():
    """2페이지: 검색 결과"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 검색 파라미터
    player_name_raw = request.args.get('player_name', '')
    player_names = [name.strip() for name in player_name_raw.split(',') if name.strip()]
    selected_seasons = request.args.getlist('seasons')
    selected_positions = request.args.getlist('positions')  # 포지션 필터 추가
    min_ovr = request.args.get('min_ovr', '')
    max_ovr = request.args.get('max_ovr', '')
    min_salary = request.args.get('min_salary', '')
    max_salary = request.args.get('max_salary', '')
    preferred_foot = request.args.get('preferred_foot', '')
    weak_foot_min = request.args.get('weak_foot_min', '')
    min_height = request.args.get('min_height', '')
    max_height = request.args.get('max_height', '')
    min_weight = request.args.get('min_weight', '')
    max_weight = request.args.get('max_weight', '')
    selected_body_types = request.args.getlist('body_types')
    new_trait = request.args.get('new_trait', '')
    normal_trait_1 = request.args.get('normal_trait_1', '')
    normal_trait_2 = request.args.get('normal_trait_2', '')
    normal_trait_3 = request.args.get('normal_trait_3', '')
    nation_team_color = request.args.get('nation_team_color', '')
    club_team_color_1 = request.args.get('club_team_color_1', '')
    club_team_color_2 = request.args.get('club_team_color_2', '')
    trait_team_color = request.args.get('trait_team_color', '')
    
    # 페이지네이션 파라미터
    page = 1
    per_page = 100
    offset = 0
    
    # 기본 쿼리
    query = """
    SELECT spid, player_name, season_name, overall, position,
           full_data->'image_info'->>'mini_faceon' as image,
           full_data->'image_info'->>'season_img' as season_img,
           full_data->'image_info'->>'nation_img' as nation_img,
           full_data->'game_info'->>'salary' as salary,
           full_data->'basic_info'->>'nation' as nation,
           full_data->'stats_info'->'main_overall'->'preferred_positions' as preferred_positions,
           full_data->'game_info'->>'preferred_foot' as preferred_foot,
           full_data->'game_info'->>'weak_foot' as weak_foot,
           full_data->'basic_info'->>'height' as height,
           full_data->'basic_info'->>'weight' as weight,
           full_data->'basic_info'->>'body_type' as body_type,
           full_data->'game_info'->>'skill_moves' as skill_moves,
           full_data->'game_info'->'traits' as traits
    FROM player_cards
    WHERE 1=1
    """
    params = []
    
    # 검색 조건 추가
    if player_names:
        name_conditions = []
        for name in player_names:
            name_conditions.append("player_name ILIKE %s")
            params.append(f'%{name}%')
        query += f" AND ({' OR '.join(name_conditions)})"
    
    # 시즌 필터링 - 전체의 80% 이상 선택 시 필터 미적용
    total_seasons = 131  # 전체 시즌 수
    if selected_seasons and len(selected_seasons) < int(total_seasons * 0.8):
    # season_id로 spid 앞 3자리 매칭
        season_conditions = []
        for season_id in selected_seasons:
            season_conditions.append("LEFT(spid::text, 3) = %s")
            params.append(str(season_id))
        query += f" AND ({' OR '.join(season_conditions)})"
    # 80% 이상이거나 비어있으면 모든 시즌 검색
    
    # 포지션 필터링 - main_overall 경로 사용
    if selected_positions:
        position_conditions = []
        for pos in selected_positions:
            position_conditions.append("""
                EXISTS (
                    SELECT 1 
                    FROM jsonb_array_elements(
                        player_cards.full_data->'stats_info'->'main_overall'->'preferred_positions'             
                    ) AS pp
                    WHERE pp->>'position' = %s
                )
            """)
            params.append(pos)
        
        query += f" AND ({' OR '.join(position_conditions)})"
    
    if min_ovr:
        query += " AND overall >= %s"
        params.append(int(min_ovr))
        
    if max_ovr:
        query += " AND overall <= %s"
        params.append(int(max_ovr))
        
    if min_salary:
        query += " AND CAST(player_cards.full_data->'game_info'->>'salary' AS INTEGER) >= %s"
        params.append(int(min_salary))
    
    if max_salary:
        query += " AND CAST(player_cards.full_data->'game_info'->>'salary' AS INTEGER) <= %s"
        params.append(int(max_salary))
        
    if preferred_foot:
        if preferred_foot == 'left':
            query += " AND player_cards.full_data->'game_info'->>'preferred_foot' ILIKE %s"
            params.append('%L%')
        elif preferred_foot == 'right':
            query += " AND player_cards.full_data->'game_info'->>'preferred_foot' ILIKE %s"
            params.append('%R%')
            
    if weak_foot_min:
        query += """ AND (
            SELECT CAST(regexp_replace(
                player_cards.full_data->'game_info'->>'weak_foot', 
                '[^0-9]', '', 'g'
            ) AS INTEGER)
        ) >= %s"""
        params.append(int(weak_foot_min)) 
        
    if min_height:
        query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) >= %s"""
        params.append(int(min_height))

    if max_height:
        query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) <= %s"""
        params.append(int(max_height))

    if min_weight:
        query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) >= %s"""
        params.append(int(min_weight))

    if max_weight:
        query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) <= %s"""
        params.append(int(max_weight))
        
    if selected_body_types:
        body_type_conditions = []
        for body_type in selected_body_types:
            body_type_conditions.append("player_cards.full_data->'basic_info'->>'body_type' = %s")
            params.append(body_type)
        query += f" AND ({' OR '.join(body_type_conditions)})"
        
    selected_traits = []
    if new_trait:
        selected_traits.append(new_trait)
    if normal_trait_1:
        selected_traits.append(normal_trait_1)
    if normal_trait_2:
        selected_traits.append(normal_trait_2)
    if normal_trait_3:
        selected_traits.append(normal_trait_3)

    if selected_traits:
        for trait in selected_traits:
            query += """ AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(player_cards.full_data->'game_info'->'traits') AS trait
                WHERE trait = %s
            )"""
            params.append(trait) 
            
    if nation_team_color:
        query += " AND player_cards.full_data->'basic_info'->>'nation' LIKE %s"
        params.append(f'%{nation_team_color}%')
        
    if club_team_color_1:
        query += """ AND EXISTS (
           SELECT 1
            FROM jsonb_array_elements(player_cards.full_data->'basic_info'->'club_history') AS club_hist
            WHERE club_hist->>'club' = %s
        )"""
        params.append(club_team_color_1)
         
    if club_team_color_2:
        query += """ AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(player_cards.full_data->'basic_info'->'club_history') AS club_hist
            WHERE club_hist->>'club' = %s
        )"""
        params.append(club_team_color_2)
        
    if trait_team_color:
        query += """ AND RIGHT(player_cards.spid::text, 6) IN (
            SELECT player_id
            FROM special_teamcolor_players
            WHERE teamcolor_id = (
                SELECT id FROM special_teamcolors WHERE name = %s
            )
        )"""
        params.append(trait_team_color)    
                                              
    
    # 전체 카드 수 계산
    count_query = """
    SELECT COUNT(*)
    FROM player_cards
    WHERE 1=1
    """
    count_params = []
    
    # 검색 조건 재적용
    if player_names:
       name_conditions = []
       for name in player_names:
           name_conditions.append("player_name ILIKE %s")
           count_params.append(f'%{name}%')
       count_query += f" AND ({' OR '.join(name_conditions)})"   
    
    total_seasons = 131
    if selected_seasons and len(selected_seasons) < int(total_seasons * 0.8):
    # season_id로 spid 앞 3자리 매칭
        season_conditions = []
        for season_id in selected_seasons:
            season_conditions.append("LEFT(spid::text, 3) = %s")
            count_params.append(str(season_id))
        count_query += f" AND ({' OR '.join(season_conditions)})"
    
    if selected_positions:
        position_conditions = []
        for pos in selected_positions:
            position_conditions.append("""
                EXISTS (
                    SELECT 1 
                    FROM jsonb_array_elements(
                        player_cards.full_data->'stats_info'->'main_overall'->'preferred_positions'
                    ) AS pp
                    WHERE pp->>'position' = %s
                )
            """)
            count_params.append(pos)
        count_query += f" AND ({' OR '.join(position_conditions)})"
    
    if min_ovr:
        count_query += " AND overall >= %s"
        count_params.append(int(min_ovr))
        
    if max_ovr:
        count_query += " AND overall <= %s"
        count_params.append(int(max_ovr))
        
    if min_salary:
        count_query += " AND CAST(player_cards.full_data->'game_info'->>'salary' AS INTEGER) >= %s"
        count_params.append(int(min_salary))
    
    if max_salary:
        count_query += " AND CAST(player_cards.full_data->'game_info'->>'salary' AS INTEGER) <= %s"
        count_params.append(int(max_salary))
        
    if preferred_foot:
        if preferred_foot == 'left':
            count_query += " AND player_cards.full_data->'game_info'->>'preferred_foot' ILIKE %s"
            count_params.append('%L%')
        elif preferred_foot == 'right':
            count_query += " AND player_cards.full_data->'game_info'->>'preferred_foot' ILIKE %s"
            count_params.append('%R%')

    if weak_foot_min:
        count_query += """ AND (
            SELECT CAST(regexp_replace(
                player_cards.full_data->'game_info'->>'weak_foot', 
                '[^0-9]', '', 'g'
            ) AS INTEGER)
        ) >= %s"""
        count_params.append(int(weak_foot_min))
        
    if min_height:
        count_query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) >= %s"""
        count_params.append(int(min_height))

    if max_height:
        count_query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) <= %s"""
        count_params.append(int(max_height))

    if min_weight:
        count_query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) >= %s"""
        count_params.append(int(min_weight))

    if max_weight:
        count_query += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) <= %s"""
        count_params.append(int(max_weight))
        
    if selected_body_types:
        body_type_conditions = []
        for body_type in selected_body_types:
            body_type_conditions.append("player_cards.full_data->'basic_info'->>'body_type' = %s")
            count_params.append(body_type)
        count_query += f" AND ({' OR '.join(body_type_conditions)})"
        
    selected_traits = []
    if new_trait:
        selected_traits.append(new_trait)
    if normal_trait_1:
        selected_traits.append(normal_trait_1)
    if normal_trait_2:
        selected_traits.append(normal_trait_2)
    if normal_trait_3:
        selected_traits.append(normal_trait_3)

    if selected_traits:
        for trait in selected_traits:
            count_query += """ AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(player_cards.full_data->'game_info'->'traits') AS trait
                WHERE trait = %s
            )"""
            count_params.append(trait)
            
    if nation_team_color:
        count_query += " AND player_cards.full_data->'basic_info'->>'nation' LIKE %s"
        count_params.append(f'%{nation_team_color}%')  
        
    if club_team_color_1:
        count_query += """ AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(player_cards.full_data->'basic_info'->'club_history') AS club_hist
            WHERE club_hist->>'club' = %s
        )"""
        count_params.append(club_team_color_1)   
        
    if club_team_color_2:
        count_query += """ AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(player_cards.full_data->'basic_info'->'club_history') AS club_hist
            WHERE club_hist->>'club' = %s
        )"""
        count_params.append(club_team_color_2)    
        
    if trait_team_color:
        count_query += """ AND RIGHT(player_cards.spid::text, 6) IN (
            SELECT player_id
            FROM special_teamcolor_players
            WHERE teamcolor_id = (
                SELECT id FROM special_teamcolors WHERE name = %s
            )
        )"""
        count_params.append(trait_team_color)     
        
                          
    cur.execute(count_query, count_params)
    
    total_count = cur.fetchone()['count']
    total_pages = max(1, (total_count + per_page - 1) // per_page) if total_count > 0 else 1
    
    # 정렬 및 페이지네이션 적용
    query += " ORDER BY overall DESC, player_name"
    query += " LIMIT %s OFFSET %s"
    params.extend([per_page, offset])
    
    cur.execute(query, params)
    cards = cur.fetchall()
    
    cur.close()
    conn.close()
    
    is_limited = total_count > per_page
    
    return render_template('results.html', 
                         cards=cards,
                         total_count=total_count,
                         current_page=1,  # 항상 1페이지
                         total_pages=1,   # 페이지네이션 제거
                         per_page=per_page,
                         is_limited=is_limited,  # 제한 여부 전달
                         search_params=request.args)
    
    
    
@app.route('/compare/<int:spid1>/<int:spid2>')
def compare_cards(spid1, spid2):
    """카드 비교 페이지"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 두 카드의 전체 데이터 조회 (card_detail.html과 동일한 방식)
    cur.execute("""
        SELECT pc.*, 
               pc.full_data->'basic_info' as basic_info,
               pc.full_data->'game_info' as game_info,
               pc.full_data->'stats_info' as stats_info,
               pc.full_data->'image_info' as image_info,
               cp.bp1, cp.bp2, cp.bp3, cp.bp4, cp.bp5, cp.bp6, cp.bp7,
               cp.bp8, cp.bp9, cp.bp10, cp.bp11, cp.bp12, cp.bp13
        FROM player_cards pc
        LEFT JOIN card_prices cp ON pc.spid = cp.spid
        WHERE pc.spid IN (%s, %s)
        ORDER BY pc.spid = %s DESC
    """, (spid1, spid2, spid1))
    
    cards = cur.fetchall()
    
    cur.close()
    conn.close()
    
    if len(cards) != 2:
        return "카드를 찾을 수 없습니다", 404
    
    return render_template('compare.html', card1=cards[0], card2=cards[1])    
    
    

@app.route('/card/<int:spid>')
def card_detail(spid):
    """3페이지: 카드 상세 정보"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # card_prices 테이블 JOIN 추가
    cur.execute("""
        SELECT pc.*, 
               pc.full_data->'basic_info' as basic_info,
               pc.full_data->'game_info' as game_info,
               pc.full_data->'stats_info' as stats_info,
               pc.full_data->'image_info' as image_info,
               cp.bp1, cp.bp2, cp.bp3, cp.bp4, cp.bp5, cp.bp6, cp.bp7,
               cp.bp8, cp.bp9, cp.bp10, cp.bp11, cp.bp12, cp.bp13
        FROM player_cards pc
        LEFT JOIN card_prices cp ON pc.spid = cp.spid
        WHERE pc.spid = %s
    """, (spid,))
    
    card = cur.fetchone()

    POSITION_ORDER = ['ST', 'W', 'CF', 'CAM', 'M', 'CM', 'CDM', 'WB', 'B', 'CB', 'SW', 'GK']

     # 요약 스탯 순서 추가
    if card and card['stats_info']['main_overall']['card_position'] == 'GK':
        SUMMARY_ORDER = ['다이빙', '핸들링', '킥', '반응속도', '스피드', '위치선정']
        # 골키퍼용 세부 스탯 순서
        DETAILED_ORDER = [
            'GK 다이빙', 'GK 핸들링', 'GK 킥', 'GK 반응속도', 'GK 위치 선정',
            '속력', '가속력', '골 결정력', '슛 파워', '중거리 슛', '위치 선정', '발리슛',
            '페널티 킥', '짧은 패스', '시야', '크로스', '긴 패스', '프리킥', '커브',
            '드리블', '볼 컨트롤', '민첩성', '밸런스', '반응 속도', '대인 수비', '태클',
            '가로채기', '헤더', '슬라이딩 태클', '몸싸움', '스태미너', '적극성', '점프', '침착성'
        ]
    else:
        SUMMARY_ORDER = ['스피드', '슛', '패스', '드리블', '수비', '피지컬']
        # 필드 플레이어용 세부 스탯 순서
        DETAILED_ORDER = [
            '속력', '가속력', '골 결정력', '슛 파워', '중거리 슛', '위치 선정', '발리슛',
            '페널티 킥', '짧은 패스', '시야', '크로스', '긴 패스', '프리킥', '커브',
            '드리블', '볼 컨트롤', '민첩성', '밸런스', '반응 속도', '대인 수비', '태클',
            '가로채기', '헤더', '슬라이딩 태클', '몸싸움', '스태미너', '적극성', '점프',
            '침착성', 'GK 다이빙', 'GK 핸들링', 'GK 킥', 'GK 반응속도', 'GK 위치 선정'
        ]
    
    cur.close()
    conn.close()
    
    if not card:
        return "카드를 찾을 수 없습니다", 404
    
    return render_template('card_detail.html', card=card, 
                                               position_order=POSITION_ORDER,
                                               summary_order=SUMMARY_ORDER,
                                               detailed_order=DETAILED_ORDER)

@app.route('/test')
def test_db():
    """DB 연결 테스트 페이지"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 간단한 테스트 쿼리들
    results = {}
    
    # 1. player_cards 테이블 확인
    cur.execute("SELECT COUNT(*) as count FROM player_cards")
    results['total_cards'] = cur.fetchone()['count']
    
    # 2. 샘플 데이터 5개 가져오기
    cur.execute("""
        SELECT spid, player_name, season_name, overall, position 
        FROM player_cards 
        LIMIT 5
    """)
    results['sample_cards'] = cur.fetchall()
    
    # 3. 시즌 정보 확인
    cur.execute("SELECT COUNT(*) as count FROM seasons")
    results['total_seasons'] = cur.fetchone()['count']
    
    # 4. 컬럼 확인
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'player_cards'
    """)
    results['columns'] = [row['column_name'] for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return jsonify(results)

@app.route('/api/stats')
def api_stats():
    """통계 API"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 선수별 최고 오버롤
    cur.execute("""
        SELECT player_name, MAX(overall) as max_overall, COUNT(*) as card_count
        FROM player_cards
        GROUP BY player_name
        ORDER BY max_overall DESC
    """)
    player_stats = cur.fetchall()
    
    # 시즌별 카드 수
    cur.execute("""
        SELECT season_name, COUNT(*) as count
        FROM player_cards
        GROUP BY season_name
        ORDER BY count DESC
    """)
    season_stats = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return jsonify({
        'player_stats': player_stats,
        'season_stats': season_stats
    })
    
    
@app.route('/community/vote/<int:post_id>/<vote_type>', methods=['POST'])
def vote_post(post_id, vote_type):
    """게시글 추천/비추천"""
    if vote_type not in ['like', 'dislike']:
        return jsonify({'success': False, 'message': '잘못된 요청입니다'}), 400
    
    # IP 해시 생성
    ip_hash = hash_ip(request.remote_addr)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 이미 투표했는지 확인
        cur.execute("""
            SELECT vote_type FROM community.post_votes 
            WHERE post_id = %s AND ip_hash = %s
        """, (post_id, ip_hash))
        
        existing_vote = cur.fetchone()
        
        if existing_vote:
            return jsonify({
                'success': False, 
                'message': '이미 투표하셨습니다'
            }), 400
        
        # 투표 기록 저장
        cur.execute("""
            INSERT INTO community.post_votes (post_id, ip_hash, vote_type)
            VALUES (%s, %s, %s)
        """, (post_id, ip_hash, vote_type))
        
        # 게시글의 추천/비추천 수 업데이트
        if vote_type == 'like':
            cur.execute("""
                UPDATE community.posts 
                SET likes = likes + 1 
                WHERE id = %s
            """, (post_id,))
        else:
            cur.execute("""
                UPDATE community.posts 
                SET dislikes = dislikes + 1 
                WHERE id = %s
            """, (post_id,))
        
        # 순추천 계산 및 인기글 등록
        cur.execute("""
            UPDATE community.posts 
            SET is_popular = (likes - dislikes >= 5)
            WHERE id = %s
        """, (post_id,))
        
        conn.commit()
        
        # 업데이트된 정보 가져오기
        cur.execute("""
            SELECT likes, dislikes, (likes - dislikes) as net_votes 
            FROM community.posts 
            WHERE id = %s
        """, (post_id,))
        
        result = cur.fetchone()
        
        return jsonify({
            'success': True,
            'likes': result['likes'],
            'dislikes': result['dislikes'],
            'net_votes': result['net_votes']
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    finally:
        cur.close()
        conn.close()    
    

@app.route('/player_review/<int:spid>')
def player_review(spid):
    """선수 후기 페이지"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 선수 카드 정보 조회
    cur.execute("""
        SELECT pc.*, 
               pc.full_data->'basic_info' as basic_info,
               pc.full_data->'image_info' as image_info
        FROM player_cards pc
        WHERE pc.spid = %s
    """, (spid,))
    
    card = cur.fetchone()
    
    if not card:
        cur.close()
        conn.close()
        return "선수 카드를 찾을 수 없습니다", 404
    
    # ✅ 후기 조회 (사용자 이름 포함)
    cur.execute("""
        SELECT pr.*, u.name as author_name, u.email as author_email
        FROM player_reviews pr
        JOIN users u ON pr.user_id = u.id
        WHERE pr.spid = %s
        ORDER BY pr.created_at DESC
    """, (spid,))
    
    reviews = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('player_review.html', card=card, reviews=reviews)


@app.route('/player_review/<int:spid>/comment', methods=['POST'])
@login_required  # ✅ 로그인 필수
def add_player_review(spid):
    """선수 후기 작성"""
    content = request.form.get('content')
    rating = request.form.get('rating') or None
    
    if not content:
        return redirect(f'/player_review/{spid}')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # ✅ user_id 사용 (current_user에서 가져옴)
    cur.execute("""
        INSERT INTO player_reviews (spid, user_id, content, rating)
        VALUES (%s, %s, %s, %s)
    """, (spid, current_user.id, content, rating))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(f'/player_review/{spid}')


@app.route('/login')
def login():
    """로그인 페이지"""
    return render_template('login.html')

@app.route('/login/google/authorized')
def google_authorized():
    """구글 로그인 콜백"""
    if not google.authorized:
        return redirect(url_for('login'))
    
    # 구글에서 사용자 정보 가져오기
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return redirect(url_for('login'))
    
    user_info = resp.json()
    email = user_info['email']
    name = user_info.get('name', '')
    profile_image = user_info.get('picture', '')
    oauth_id = user_info['id']
    
    # DB에서 사용자 확인/생성
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 기존 사용자 확인
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    
    if user:
        # 기존 사용자 - 마지막 로그인 시간 업데이트
        cur.execute("""
            UPDATE users 
            SET last_login = CURRENT_TIMESTAMP, profile_image = %s
            WHERE id = %s
        """, (profile_image, user['id']))
        conn.commit()
        user_id = user['id']
    else:
        # 신규 사용자 - 생성
        cur.execute("""
            INSERT INTO users (email, name, profile_image, oauth_provider, oauth_id, last_login)
            VALUES (%s, %s, %s, 'google', %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, (email, name, profile_image, oauth_id))
        user_id = cur.fetchone()['id']
        conn.commit()
    
    cur.close()
    conn.close()
    
    # Flask-Login으로 로그인 처리
    user_obj = User(user_id, email, name, profile_image)
    login_user(user_obj)
    
    return redirect('/')

@app.route('/logout')
@login_required
def logout():
    """로그아웃"""
    logout_user()
    return redirect('/')

@app.route('/profile')
@login_required
def profile():
    """프로필 페이지 (테스트용)"""
    return f"""
    <h1>프로필</h1>
    <p>이메일: {current_user.email}</p>
    <p>이름: {current_user.name}</p>
    <p><a href="/logout">로그아웃</a></p>
    """


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)