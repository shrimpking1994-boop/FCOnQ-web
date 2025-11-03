"""
FC온라인 선수 카드 웹 애플리케이션
Flask + PostgreSQL
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from functools import wraps
from authlib.integrations.flask_client import OAuth
import os
from datetime import timedelta
from dotenv import load_dotenv  # ← 추가!
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import hashlib

# .env 파일 로드  # ← 추가!
load_dotenv()       # ← 추가!

app = Flask(__name__)

# Flask 세션 설정 (OAuth에 필요)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# OAuth 설정
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# DB 연결 설정
DB_CONFIG = {
    "host": os.getenv('DB_HOST', 'localhost'),
    "database": os.getenv('DB_NAME', 'fconline'),
    "user": os.getenv('DB_USER', 'postgres'),
    "password": os.getenv('DB_PASSWORD', '9787')
}

# IP 해싱 함수
def hash_ip(ip_address):
    """IP 주소를 해시 처리 (개인정보 보호)"""
    secret = "fconline_secret_key_2025"  # 비밀키 (변경 가능)
    return hashlib.sha256(f"{ip_address}{secret}".encode()).hexdigest()

def format_ip_display(ip):
    """IP를 디시인사이드 스타일로 표시 (앞부분만)"""
    if not ip:
        return ''
    
    if '.' in ip:
        parts = ip.split('.')
        if len(parts) >= 2:
            return f"({parts[0]}.{parts[1]})"
    
    return f"({ip[:8]})"

def hash_password(password):
    """비밀번호를 해시 처리"""
    if not password:
        return None
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """비밀번호 검증"""
    if not password or not password_hash:
        return False
    return hash_password(password) == password_hash

def admin_required(f):
    """관리자 권한 확인 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') != 'admin':
            return jsonify({'success': False, 'message': '관리자 권한이 필요합니다'}), 403
        return f(*args, **kwargs)
    return decorated_function


# 시즌 정렬 순서 (공식 홈페이지 기준)
SEASON_ORDER = [
    100, 110, 101, 113, 114, 111, 851, 848, 850, 846, 845, 849, 840,
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
    277, 257, 239, 517, 515, 513, 511, 508, 506, 503, 502,
    501, 500, 300, 324, 323, 322, 321, 320, 319, 318, 317,
    812
]

def get_db_connection():
    """DB 연결 생성"""
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    return conn

def build_search_conditions(player_names, selected_seasons, selected_positions, min_ovr, max_ovr,
                            min_salary, max_salary, preferred_foot, weak_foot_min, min_height, max_height,
                            min_weight, max_weight, selected_body_types, selected_traits, nation_team_color,
                            club_team_color_1, club_team_color_2, trait_team_color):
    """검색 조건 SQL 문자열과 파라미터 생성 (재사용 가능)"""
    conditions = ""
    params = []
    
    # 선수 이름
    if player_names:
        name_conditions = []
        for name in player_names:
            name_conditions.append("player_name ILIKE %s")
            params.append(f'%{name}%')
        conditions += f" AND ({' OR '.join(name_conditions)})"
    
    # 시즌 필터링 (선택된 경우만)
    if selected_seasons:
        season_conditions = []
        for season_id in selected_seasons:
            season_conditions.append("LEFT(spid::text, 3) = %s")
            params.append(str(season_id))
        conditions += f" AND ({' OR '.join(season_conditions)})"
    # 시즌 미선택 시 조건 추가 안 함 (전체 검색)    
    
    # 포지션 필터링
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
        conditions += f" AND ({' OR '.join(position_conditions)})"
    
    # 오버롤
    if min_ovr:
        conditions += " AND overall >= %s"
        params.append(int(min_ovr))
    if max_ovr:
        conditions += " AND overall <= %s"
        params.append(int(max_ovr))
    
    # 급여
    if min_salary:
        conditions += " AND CAST(player_cards.full_data->'game_info'->>'salary' AS INTEGER) >= %s"
        params.append(int(min_salary))
    if max_salary:
        conditions += " AND CAST(player_cards.full_data->'game_info'->>'salary' AS INTEGER) <= %s"
        params.append(int(max_salary))
    
    # 주발
    if preferred_foot:
        if preferred_foot == 'left':
            conditions += " AND player_cards.full_data->'game_info'->>'preferred_foot' ILIKE %s"
            params.append('%L%')
        elif preferred_foot == 'right':
            conditions += " AND player_cards.full_data->'game_info'->>'preferred_foot' ILIKE %s"
            params.append('%R%')
    
    # 약발
    if weak_foot_min:
        conditions += """ AND (
            SELECT CAST(regexp_replace(
                player_cards.full_data->'game_info'->>'weak_foot', 
                '[^0-9]', '', 'g'
            ) AS INTEGER)
        ) >= %s"""
        params.append(int(weak_foot_min))
    
    # 키
    if min_height:
        conditions += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) >= %s"""
        params.append(int(min_height))
    if max_height:
        conditions += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) <= %s"""
        params.append(int(max_height))
    
    # 몸무게
    if min_weight:
        conditions += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) >= %s"""
        params.append(int(min_weight))
    if max_weight:
        conditions += """ AND CAST(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ) AS INTEGER) <= %s"""
        params.append(int(max_weight))
    
    # 체형
    if selected_body_types:
        body_type_conditions = []
        for body_type in selected_body_types:
            body_type_conditions.append("player_cards.full_data->'basic_info'->>'body_type' = %s")
            params.append(body_type)
        conditions += f" AND ({' OR '.join(body_type_conditions)})"
    
    # 특성
    if selected_traits:
        for trait in selected_traits:
            conditions += """ AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(player_cards.full_data->'game_info'->'traits') AS trait
                WHERE trait = %s
            )"""
            params.append(trait)
    
    # 국가 팀컬러
    if nation_team_color:
        conditions += " AND player_cards.full_data->'basic_info'->>'nation' LIKE %s"
        params.append(f'%{nation_team_color}%')
    
    # 클럽 팀컬러 1
    if club_team_color_1:
        conditions += """ AND EXISTS (
           SELECT 1
            FROM jsonb_array_elements(player_cards.full_data->'basic_info'->'club_history') AS club_hist
            WHERE club_hist->>'club' = %s
        )"""
        params.append(club_team_color_1)
    
    # 클럽 팀컬러 2
    if club_team_color_2:
        conditions += """ AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(player_cards.full_data->'basic_info'->'club_history') AS club_hist
            WHERE club_hist->>'club' = %s
        )"""
        params.append(club_team_color_2)
    
    # 특성 팀컬러
    if trait_team_color:
        conditions += """ AND RIGHT(player_cards.spid::text, 6) IN (
            SELECT player_id
            FROM special_teamcolor_players
            WHERE teamcolor_id = (
                SELECT id FROM special_teamcolors WHERE name = %s
            )
        )"""
        params.append(trait_team_color)
    
    return conditions, params


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
    
    # 관리자 여부 확인
    is_admin = session.get('user_role') == 'admin'

    # 일반 사용자는 삭제되지 않은 글만 보기
    if not is_admin:
        conditions.append("is_deleted = false")

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
        post['ip_display'] = format_ip_display(post.get('author_ip'))
    
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
        
        # 로그인 여부 확인
        if 'user_id' in session:
            # 로그인 상태: 세션 정보 사용
            author = session.get('user_name', '익명')
            author_ip = None  # 로그인 유저는 IP 저장 안 함
            password_hash = None  # 로그인 유저는 비밀번호 불필요
            user_id = session.get('user_id')  # 작성자 ID 저장
        else:
            # 비로그인 상태: 폼 데이터 사용
            author = request.form.get('author', '익명')
            password = request.form.get('password', '')
            author_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
            password_hash = hash_password(password) if password else None
            user_id = None
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO community.posts (category, title, content, author, author_ip, password_hash, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (category, title, content, author, author_ip, password_hash, user_id))
        
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

    # 삭제된 게시글 접근 제한 (관리자는 제외)
    if post.get('is_deleted') and session.get('user_role') != 'admin':
        cur.close()
        conn.close()
        return "삭제된 게시글입니다", 403
    
    # 메인 게시글 IP 표시 추가
    post['ip_display'] = format_ip_display(post.get('author_ip'))
    
    
    # 관리자 여부 확인
    is_admin = session.get('user_role') == 'admin'

    # 댓글 조회 (일반 사용자는 삭제되지 않은 댓글만)
    if is_admin:
        cur.execute("""
            SELECT * FROM community.comments 
            WHERE post_id = %s 
            ORDER BY created_at ASC
        """, (post_id,))
    else:
        cur.execute("""
            SELECT * FROM community.comments 
            WHERE post_id = %s AND is_deleted = false
            ORDER BY created_at ASC
        """, (post_id,))    
    comments = cur.fetchall()
    
    for comment in comments:
        comment['ip_display'] = format_ip_display(comment.get('author_ip'))
    
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
            SELECT id, category, title, author, author_ip, created_at, views, likes, content
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
            SELECT id, category, title, author, author_ip, created_at, views, likes, content
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
        # IP 표시 추가
        p['ip_display'] = format_ip_display(p.get('author_ip'))
    
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
    
    # 로그인 여부 확인
    if 'user_id' in session:
        # 로그인 상태: 세션 정보 사용
        author = session.get('user_name', '익명')
        author_ip = None  # 로그인 유저는 IP 저장 안 함
        password_hash = None  # 로그인 유저는 비밀번호 불필요
        user_id = session.get('user_id')
    else:
        # 비로그인 상태: 폼 데이터 사용
        author = request.form.get('author', '익명')
        password = request.form.get('password', '')
        author_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        password_hash = hash_password(password) if password else None
        user_id = None
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO community.comments (post_id, content, author, author_ip, password_hash, user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (post_id, content, author, author_ip, password_hash, user_id))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(f'/community/post/{post_id}')

@app.route('/community/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    """게시글 삭제"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 게시글 조회
    cur.execute("SELECT password_hash, user_id FROM community.posts WHERE id = %s", (post_id,))
    post = cur.fetchone()
    
    if not post:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': '게시글을 찾을 수 없습니다'}), 404
    
    # 권한 확인
    if post['user_id']:
        # 로그인 유저가 작성한 글: 세션 user_id 확인
        if 'user_id' not in session or session['user_id'] != post['user_id']:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '본인이 작성한 글만 삭제할 수 있습니다'}), 403
    else:
        # 비로그인 유저가 작성한 글: 비밀번호 확인
        password = request.form.get('password', '')
        if not verify_password(password, post['password_hash']):
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다'}), 403
    
    # 댓글 먼저 삭제
    cur.execute("DELETE FROM community.comments WHERE post_id = %s", (post_id,))
    
    # 게시글 삭제
    cur.execute("DELETE FROM community.posts WHERE id = %s", (post_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'message': '게시글이 삭제되었습니다'})


@app.route('/community/post/<int:post_id>/admin_delete', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    """관리자 전용 게시글 삭제 (Soft Delete)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 게시글 존재 확인
        cur.execute("SELECT id FROM community.posts WHERE id = %s", (post_id,))
        post = cur.fetchone()
        
        if not post:
            return jsonify({'success': False, 'message': '게시글을 찾을 수 없습니다'}), 404
        
        # Soft Delete: is_deleted를 true로 설정
        cur.execute("""
            UPDATE community.posts 
            SET is_deleted = true, 
                deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s
            WHERE id = %s
        """, (session.get('user_id'), post_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': '게시글이 삭제되었습니다'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'삭제 중 오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/community/comment/<int:comment_id>/admin_delete', methods=['POST'])
@admin_required
def admin_delete_comment(comment_id):
    """관리자 전용 댓글 삭제 (Soft Delete)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 댓글 존재 확인
        cur.execute("SELECT id, post_id FROM community.comments WHERE id = %s", (comment_id,))
        comment = cur.fetchone()
        
        if not comment:
            return jsonify({'success': False, 'message': '댓글을 찾을 수 없습니다'}), 404
        
        # Soft Delete: is_deleted를 true로 설정
        cur.execute("""
            UPDATE community.comments 
            SET is_deleted = true, 
                deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s
            WHERE id = %s
        """, (session.get('user_id'), comment_id))
        
        conn.commit()
        return jsonify({
            'success': True, 
            'message': '댓글이 삭제되었습니다',
            'post_id': comment['post_id']
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'삭제 중 오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/community/comment/<int:comment_id>/delete', methods=['POST'])
def delete_comment(comment_id):
    """댓글 삭제"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 댓글 조회
    cur.execute("SELECT password_hash, post_id, user_id FROM community.comments WHERE id = %s", (comment_id,))
    comment = cur.fetchone()
    
    if not comment:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': '댓글을 찾을 수 없습니다'}), 404
    
    # 권한 확인
    if comment['user_id']:
        # 로그인 유저가 작성한 댓글: 세션 user_id 확인
        if 'user_id' not in session or session['user_id'] != comment['user_id']:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '본인이 작성한 댓글만 삭제할 수 있습니다'}), 403
    else:
        # 비로그인 유저가 작성한 댓글: 비밀번호 확인
        password = request.form.get('password', '')
        if not verify_password(password, comment['password_hash']):
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다'}), 403
    
    # 댓글 삭제
    cur.execute("DELETE FROM community.comments WHERE id = %s", (comment_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'message': '댓글이 삭제되었습니다', 'post_id': comment['post_id']})


@app.route('/community/post/<int:post_id>/edit')
def edit_post_page(post_id):
    """게시글 수정 페이지"""
    password = request.args.get('password', '')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 게시글 조회
    cur.execute("SELECT * FROM community.posts WHERE id = %s", (post_id,))
    post = cur.fetchone()
    
    if not post:
        cur.close()
        conn.close()
        return "게시글을 찾을 수 없습니다", 404
    
    # 비밀번호 확인
    if not verify_password(password, post['password_hash']):
        cur.close()
        conn.close()
        return """
            <script>
                alert('비밀번호가 일치하지 않습니다');
                history.back();
            </script>
        """
    
    cur.close()
    conn.close()
    
    return render_template('community_edit.html', post=post)


@app.route('/community/post/<int:post_id>/edit', methods=['POST'])
def edit_post_submit(post_id):
    """게시글 수정 처리"""
    category = request.form.get('category')
    title = request.form.get('title')
    content = request.form.get('content')
    password = request.form.get('password', '')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 게시글 조회
    cur.execute("SELECT password_hash FROM community.posts WHERE id = %s", (post_id,))
    post = cur.fetchone()
    
    if not post:
        cur.close()
        conn.close()
        return "게시글을 찾을 수 없습니다", 404
    
    # 비밀번호 확인
    if not verify_password(password, post['password_hash']):
        cur.close()
        conn.close()
        return """
            <script>
                alert('비밀번호가 일치하지 않습니다');
                history.back();
            </script>
        """
    
    # 게시글 수정
    cur.execute("""
        UPDATE community.posts 
        SET category = %s, title = %s, content = %s 
        WHERE id = %s
    """, (category, title, content, post_id))
    
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
    cur.execute("SELECT position FROM positions ORDER BY position")
    positions = [row['position'] for row in cur.fetchall()]
   
    
    # 팀컬러 데이터 가져오기
    # 1. 국가 팀컬러
    cur.execute("""
        SELECT nation_name 
        FROM nation_teamcolors 
        ORDER BY nation_name
    """)
    nation_data = [row['nation_name'] for row in cur.fetchall()]
    nations_old = nation_data  # 기존 호환성
    nation_teamcolors = nation_data  # 팀컬러 필터용    
    
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
    per_page = 200
    offset = 0
    
    # 특성 리스트 생성
    selected_traits = []
    if new_trait:
        selected_traits.append(new_trait)
    if normal_trait_1:
        selected_traits.append(normal_trait_1)
    if normal_trait_2:
        selected_traits.append(normal_trait_2)
    if normal_trait_3:
        selected_traits.append(normal_trait_3)
    
    # 검색 조건 생성 (헬퍼 함수 사용)
    search_conditions, search_params = build_search_conditions(
        player_names, selected_seasons, selected_positions, min_ovr, max_ovr,
        min_salary, max_salary, preferred_foot, weak_foot_min, min_height, max_height,
        min_weight, max_weight, selected_body_types, selected_traits, nation_team_color,
        club_team_color_1, club_team_color_2, trait_team_color
    )
    
    # COUNT 쿼리 실행
    count_query = "SELECT COUNT(*) FROM player_cards WHERE 1=1" + search_conditions
    cur.execute(count_query, search_params)
    total_count = cur.fetchone()['count']
    total_pages = max(1, (total_count + per_page - 1) // per_page) if total_count > 0 else 1
    
    # 메인 쿼리 실행
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
    """ + search_conditions + """
    ORDER BY overall DESC, player_name
    LIMIT %s OFFSET %s
    """
    
    query_params = search_params + [per_page, offset]
    cur.execute(query, query_params)
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
    
    # 관리자 여부 확인
    is_admin = session.get('user_role') == 'admin'

    # 후기 조회 (일반 사용자는 삭제되지 않은 후기만)
    if is_admin:
        cur.execute("""
            SELECT * FROM player_reviews
            WHERE spid = %s
            ORDER BY created_at DESC
        """, (spid,))
    else:
        cur.execute("""
            SELECT * FROM player_reviews
            WHERE spid = %s AND is_deleted = false
            ORDER BY created_at DESC
        """, (spid,))
    reviews = cur.fetchall()
    
    # IP 표시 추가
    for review in reviews:
        review['ip_display'] = format_ip_display(review.get('author_ip'))    
    
    cur.close()
    conn.close()
    
    return render_template('player_review.html', card=card, reviews=reviews)


@app.route('/player_review/<spid>/write', methods=['POST'])
def write_player_review(spid):
    """선수 후기 작성"""
    rating = request.form.get('rating')
    rating = int(rating) if rating else None
    content = request.form.get('content')
    author = request.form.get('author', '익명')
    password = request.form.get('password', '')
    # 프록시 환경 대응 (Render 등)
    author_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    
    # 비밀번호 해시 처리
    password_hash = hash_password(password) if password else None
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO player_reviews (spid, rating, content, author, author_ip, password_hash)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (spid, rating, content, author, author_ip, password_hash))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(f'/player_review/{spid}')


@app.route('/player_review/<int:review_id>/admin_delete', methods=['POST'])
@admin_required
def admin_delete_player_review(review_id):
    """관리자 전용 선수 후기 삭제 (Soft Delete)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 후기 존재 확인
        cur.execute("SELECT id, spid FROM player_reviews WHERE id = %s", (review_id,))
        review = cur.fetchone()
        
        if not review:
            return jsonify({'success': False, 'message': '후기를 찾을 수 없습니다'}), 404
        
        # Soft Delete: is_deleted를 true로 설정
        cur.execute("""
            UPDATE player_reviews 
            SET is_deleted = true, 
                deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s
            WHERE id = %s
        """, (session.get('user_id'), review_id))
        
        conn.commit()
        return jsonify({
            'success': True, 
            'message': '후기가 삭제되었습니다',
            'spid': review['spid']
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'삭제 중 오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/player_review/<int:review_id>/delete', methods=['POST'])
def delete_player_review(review_id):
    """선수 후기 삭제"""
    password = request.form.get('password', '')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 후기 조회
    cur.execute("SELECT password_hash, spid FROM player_reviews WHERE id = %s", (review_id,))
    review = cur.fetchone()
    
    if not review:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': '후기를 찾을 수 없습니다'}), 404
    
    # 비밀번호 확인
    if not verify_password(password, review['password_hash']):
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다'}), 403
    
    # 후기 삭제
    cur.execute("DELETE FROM player_reviews WHERE id = %s", (review_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'message': '후기가 삭제되었습니다', 'spid': review['spid']})


@app.route('/player_review/vote/<int:review_id>/<vote_type>', methods=['POST'])
def vote_player_review(review_id, vote_type):
    """선수 후기 추천/비추천"""
    if vote_type not in ['like', 'dislike']:
        return jsonify({'success': False, 'message': '잘못된 요청입니다'}), 400
    
    # IP 해시 생성
    ip_hash = hash_ip(request.remote_addr)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 이미 투표했는지 확인
        cur.execute("""
            SELECT vote_type FROM player_review_votes 
            WHERE review_id = %s AND ip_hash = %s
        """, (review_id, ip_hash))
        
        existing_vote = cur.fetchone()
        
        if existing_vote:
            return jsonify({
                'success': False, 
                'message': '이미 투표하셨습니다'
            }), 400
        
        # 투표 기록 저장
        cur.execute("""
            INSERT INTO player_review_votes (review_id, ip_hash, vote_type)
            VALUES (%s, %s, %s)
        """, (review_id, ip_hash, vote_type))
        
        # 후기의 추천/비추천 수 업데이트
        if vote_type == 'like':
            cur.execute("""
                UPDATE player_reviews 
                SET likes = likes + 1 
                WHERE id = %s
            """, (review_id,))
        else:
            cur.execute("""
                UPDATE player_reviews 
                SET dislikes = dislikes + 1 
                WHERE id = %s
            """, (review_id,))
        
        conn.commit()
        
        # 업데이트된 정보 가져오기
        cur.execute("""
            SELECT likes, dislikes, (likes - dislikes) as net_votes 
            FROM player_reviews 
            WHERE id = %s
        """, (review_id,))
        
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


@app.route('/login')
def login():
    """Google OAuth 로그인 시작"""
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def auth_callback():
    """Google OAuth 콜백"""
    try:
        # Google로부터 토큰 받기
        token = google.authorize_access_token()
        
        # 사용자 정보 가져오기
        user_info = token.get('userinfo')
        
        if not user_info:
            return "사용자 정보를 가져올 수 없습니다.", 400
        
        # DB에서 사용자 확인 또는 생성
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 기존 사용자 확인
        cur.execute("""
            SELECT id, name, email, role, profile_image
            FROM public.users
            WHERE oauth_provider = 'google' AND oauth_id = %s
        """, (user_info['sub'],))
        
        user = cur.fetchone()
        
        if user:
            # 기존 사용자 - 마지막 로그인 시간 업데이트
            cur.execute("""
                UPDATE public.users
                SET last_login = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (user['id'],))
        else:
            # 신규 사용자 - 생성
            cur.execute("""
                INSERT INTO public.users (email, name, profile_image, oauth_provider, oauth_id)
                VALUES (%s, %s, %s, 'google', %s)
                RETURNING id, name, email, role, profile_image
            """, (
                user_info.get('email'),
                user_info.get('name'),
                user_info.get('picture'),
                user_info['sub']
            ))
            user = cur.fetchone()
        
        conn.commit()
        cur.close()
        conn.close()
        
        # 세션에 사용자 정보 저장
        session.permanent = True
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['user_email'] = user['email']
        session['user_role'] = user['role']
        session['user_profile_image'] = user['profile_image']
        
        # 메인 페이지로 리다이렉트
        return redirect('/')
        
    except Exception as e:
        print(f"OAuth 에러: {e}")
        return f"로그인 중 오류가 발생했습니다: {str(e)}", 500


@app.route('/logout')
def logout():
    """로그아웃"""
    session.clear()
    return redirect('/')


@app.route('/auth/status')
def auth_status():
    """로그인 상태 확인 (API)"""
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'user': {
                'name': session.get('user_name'),
                'email': session.get('user_email'),
                'role': session.get('user_role'),
                'profile_image': session.get('user_profile_image')
            }
        })
    else:
        return jsonify({'logged_in': False})

if __name__ == '__main__':
    app.run(debug=True, port=5000)