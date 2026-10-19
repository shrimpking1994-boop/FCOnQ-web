"""
FC온라인 선수 카드 웹 애플리케이션
Flask + PostgreSQL
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from functools import wraps
from authlib.integrations.flask_client import OAuth
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv  # ← 추가!
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import json
import pytz
import urllib.request
import urllib.parse
import urllib.error
import hashlib
import re
import nh3  # 커뮤니티 글 HTML 정화 (requirements.txt에 nh3 추가 필요)

# .env 파일 로드  # ← 추가!
load_dotenv()       # ← 추가!

app = Flask(__name__)

# Flask 세션 설정 (OAuth에 필요)
app.secret_key = os.getenv('SECRET_KEY')
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
    "host": os.getenv('DB_HOST'),
    "database": os.getenv('DB_NAME'),
    "user": os.getenv('DB_USER'),
    "password": os.getenv('DB_PASSWORD'),
    "connect_timeout": 10
}

# IP 해싱 함수
def hash_ip(ip_address):
    """IP 주소를 해시 처리 (개인정보 보호)"""
    secret = os.getenv('IP_HASH_SECRET', 'fconline_secret_key_2025')
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

@app.route('/.well-known/assetlinks.json')
def assetlinks():
    return app.send_static_file('.well-known/assetlinks.json')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/delete-account')
def delete_account():
    return render_template('delete_account.html')

@app.route('/service_worker.js')
def service_worker():
    return app.send_static_file('service_worker.js'), 200, {'Content-Type': 'application/javascript'}

@app.route('/sitemap.xml')
def sitemap():
    """동적 sitemap 생성"""
    from flask import Response
    from datetime import datetime
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 모든 선수 카드 spid 가져오기
    cur.execute("SELECT spid FROM player_cards ORDER BY spid")
    cards = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # XML 생성
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    # 메인 페이지들
    xml.append('  <url>')
    xml.append('    <loc>https://fconq.com/</loc>')
    xml.append('    <changefreq>daily</changefreq>')
    xml.append('    <priority>1.0</priority>')
    xml.append('  </url>')
    
    xml.append('  <url>')
    xml.append('    <loc>https://fconq.com/search</loc>')
    xml.append('    <changefreq>daily</changefreq>')
    xml.append('    <priority>0.9</priority>')
    xml.append('  </url>')
    
    xml.append('  <url>')
    xml.append('    <loc>https://fconq.com/community</loc>')
    xml.append('    <changefreq>daily</changefreq>')
    xml.append('    <priority>0.8</priority>')
    xml.append('  </url>')
    
    # 모든 선수 카드 페이지
    for card in cards:
        xml.append('  <url>')
        xml.append(f'    <loc>https://fconq.com/card/{card["spid"]}</loc>')
        xml.append('    <changefreq>weekly</changefreq>')
        xml.append('    <priority>0.7</priority>')
        xml.append('  </url>')
    
    xml.append('</urlset>')
    
    return Response('\n'.join(xml), mimetype='application/xml')


# 시즌 정렬 순서 (공식 홈페이지 기준)
SEASON_ORDER = [
    100, 110, 101, 113, 114, 111, 877, 867, 596, 864, 863, 862, 861, 852, 851, 848, 868, 850, 846, 845, 849, 840,
    839, 836, 829, 828, 827, 826, 825, 821, 815, 818,
    814, 813, 802, 801, 290, 291, 289, 283, 284, 272,
    273, 274, 270, 268, 265, 264, 858, 835, 811, 281, 261,
    256, 252, 251, 253, 249, 246, 237, 231, 233, 254,
    236, 804, 276, 262, 238, 219, 218, 217, 216, 214,
    213, 210, 207, 206, 202, 201, 854, 855, 831, 832, 807, 808,
    278, 279, 258, 259, 240, 241, 220, 222, 211, 212,
    866, 844, 820, 287, 267, 250, 230, 215, 856, 834, 810, 280,
    260, 242, 221, 234, 225, 806, 293, 294, 295, 298,
    297, 247, 518, 516, 514, 512, 510, 507, 504, 853, 830, 805,
    277, 257, 239, 517, 515, 513, 511, 508, 506, 503, 502,
    501, 500, 300, 324, 323, 322, 321, 320, 319, 318, 317,
    812
]

STAT_NAMES = [
    "속력", "가속력", "골 결정력", "슛 파워", "중거리 슛", "위치 선정", "발리슛",
    "페널티 킥", "짧은 패스", "시야", "크로스", "긴 패스", "프리킥", "커브",
    "드리블", "볼 컨트롤", "민첩성", "밸런스", "반응 속도", "대인 수비", "태클",
    "가로채기", "헤더", "슬라이딩 태클", "몸싸움", "스태미너", "적극성", "점프", "침착성",
    "GK 다이빙", "GK 핸들링", "GK 킥", "GK 반응속도", "GK 위치 선정"
]

def get_db_connection():
    """DB 연결 생성"""
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    return conn

def build_search_conditions(player_names, selected_seasons, selected_positions, min_ovr, max_ovr,
                            min_salary, max_salary, preferred_foot, weak_foot_min, min_height, max_height,
                            min_weight, max_weight, selected_body_types, selected_traits, nation_team_color,
                            club_team_color_1, club_team_color_2, trait_team_color, has_new_trait=False,
                            new_trait_list=None, normal_trait_list=None):
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
            SELECT CAST(NULLIF(regexp_replace(
                player_cards.full_data->'game_info'->>'weak_foot', 
                '[^0-9]', '', 'g'
            ), '') AS INTEGER)
        ) >= %s"""
        params.append(int(weak_foot_min))
    
    # 키
    if min_height:
        conditions += """ AND CAST(NULLIF(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ), '') AS INTEGER) >= %s"""
        params.append(int(min_height))
    if max_height:
        conditions += """ AND CAST(NULLIF(regexp_replace(
            player_cards.full_data->'basic_info'->>'height', 
            '[^0-9]', '', 'g'
        ), '') AS INTEGER) <= %s"""
        params.append(int(max_height))
    
    # 몸무게
    if min_weight:
        conditions += """ AND CAST(NULLIF(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ), '') AS INTEGER) >= %s"""
        params.append(int(min_weight))
    if max_weight:
        conditions += """ AND CAST(NULLIF(regexp_replace(
            player_cards.full_data->'basic_info'->>'weight', 
            '[^0-9]', '', 'g'
        ), '') AS INTEGER) <= %s"""
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

    # 신규 특성 종류 무관 보유 여부
    if has_new_trait:
        conditions += """ AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(player_cards.full_data->'game_info'->'traits') AS card_trait
            WHERE card_trait IN (SELECT trait_name FROM player_traits WHERE trait_type = 'new')
        )"""
        
    # 특성 OR 조건: 신규끼리 OR, 일반끼리 OR, 두 그룹 사이는 AND
    for trait_list in (new_trait_list, normal_trait_list):
        if trait_list:
            conditions += """ AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(player_cards.full_data->'game_info'->'traits') AS card_trait
                WHERE card_trait = ANY(%s)
            )"""
            params.append(list(trait_list))    
    
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
    """메인 페이지 = 홈 화면"""
    return render_template('home.html')


_home_cache = {'data': None, 'time': None}


def format_post_time(dt):
    """커뮤니티 글 시간 표시
    - 1분 미만: 방금 / 1시간 미만: N분 전 / 12시간 미만: N시간 전
    - 12~24시간: 시:분 (예: 12:38)
    - 24시간 이후: 월.일 (예: 10.13), 작년 이전 글은 연도 포함 (예: 25.12.30)
    """
    if not dt:
        return ''
    kst = pytz.timezone('Asia/Seoul')
    t = dt.replace(tzinfo=pytz.UTC) if dt.tzinfo is None else dt
    t = t.astimezone(kst)
    now = datetime.now(kst)
    sec = (now - t).total_seconds()
    if sec < 60:
        return '방금'
    if sec < 3600:
        return f'{int(sec // 60)}분 전'
    if sec < 12 * 3600:
        return f'{int(sec // 3600)}시간 전'
    if sec < 24 * 3600:
        return t.strftime('%H:%M')
    if t.year == now.year:
        return t.strftime('%m.%d')
    return t.strftime('%y.%m.%d')


def _home_date(dt):
    """홈 표시용 날짜 (커뮤니티 목록과 같은 규칙)"""
    return format_post_time(dt)


@app.route('/api/home_summary')
def home_summary():
    """홈 화면 요약 (5분간 재사용)"""
    now = datetime.now()
    if _home_cache['data'] and (now - _home_cache['time']).total_seconds() < 300:
        return jsonify(_home_cache['data'])

    conn = get_db_connection()
    cur = conn.cursor()

    # 인기 팀컬러 TOP 10
    cur.execute("""
        SELECT crawl_date,
               full_data->'_order' AS tc_order,
               full_data->'_usage' AS tc_usage,
               full_data->'_logos' AS tc_logos
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    teamcolors, tc_date, tc_prev_date = [], '', ''
    if row:
        usage = row['tc_usage'] or {}
        logos = row['tc_logos'] or {}
                # 7일 전 순위 (그날 데이터가 없으면 그 이전 중 가장 가까운 날)
        cur.execute("""
            SELECT crawl_date, full_data->'_order' AS tc_order
            FROM card_tierlist_rankings
            WHERE crawl_date <= %s
            ORDER BY crawl_date DESC, id DESC
            LIMIT 1
        """, (row['crawl_date'] - timedelta(days=7),))
        prev = cur.fetchone()
        if prev:
            tc_prev_date = f"{prev['crawl_date'].month}월 {prev['crawl_date'].day}일"
        prev_rank = {n: i for i, n in enumerate((prev['tc_order'] or []) if prev else [], 1)}

        for i, name in enumerate((row['tc_order'] or [])[:10], 1):
            cnt = usage.get(name, 0)
            if not prev_rank:
                change = None              # 비교할 과거 데이터 없음
            elif name in prev_rank:
                change = prev_rank[name] - i   # +면 상승, -면 하락, 0이면 유지
            else:
                change = 'new'
            teamcolors.append({'rank': i, 'name': name, 'count': cnt,
                               'ratio': round(cnt / 10000, 4), 'logo': logos.get(name, ''),
                               'change': change})
        tc_date = f"{row['crawl_date'].month}월 {row['crawl_date'].day}일"

    # 포지션별 신규 특성 1위
    cur.execute("SELECT source, position, trait_name, ratio, data_date FROM new_trait_stats WHERE rank = 1")
    traits = {'ranker': {}, 'nexon': {}}
    trait_dates = {}
    for r in cur.fetchall():
        traits.setdefault(r['source'], {})[r['position']] = {'name': r['trait_name'], 'ratio': r['ratio']}
        if r['data_date'] and r['source'] not in trait_dates:
            _, m, d = r['data_date'][:10].split('-')
            trait_dates[r['source']] = f"{int(m)}월 {int(d)}일"

    # 커뮤니티 최신글 (공지·업데이트 제외)
    cur.execute("""
        SELECT p.id, p.category, p.title, p.created_at,
               (SELECT COUNT(*) FROM community.comments c
                WHERE c.post_id = p.id AND c.is_deleted = false) AS comment_count
        FROM community.posts p
        WHERE p.is_deleted = false AND p.is_notice = false AND p.category <> '업데이트'
        ORDER BY p.created_at DESC
        LIMIT 9
    """)
    community = [{'id': r['id'], 'category': r['category'], 'title': r['title'],
                  'comment_count': r['comment_count'], 'date': _home_date(r['created_at'])}
                 for r in cur.fetchall()]

    # 최근 선수 후기 (답글 제외)
    cur.execute("""
        SELECT r.spid, r.rating, r.content, r.created_at, pc.player_name, s.season_img_url
        FROM player_reviews r
        LEFT JOIN player_cards pc ON pc.spid = r.spid
        LEFT JOIN seasons s ON s.season_id = CAST(LEFT(r.spid::text, 3) AS INTEGER)
        WHERE r.is_deleted = false AND r.parent_comment_id IS NULL
        ORDER BY r.created_at DESC
        LIMIT 6
    """)
    reviews = [{'spid': r['spid'], 'rating': r['rating'], 'player_name': r['player_name'] or '',
                'season_img': r['season_img_url'] or '',
                'content': (r['content'] or '')[:80], 'date': _home_date(r['created_at'])}
               for r in cur.fetchall()]

    # 업데이트
    cur.execute("""
        SELECT id, title, created_at FROM community.posts
        WHERE is_deleted = false AND category = '업데이트'
        ORDER BY created_at DESC
        LIMIT 5
    """)
    updates = [{'id': r['id'], 'title': r['title'], 'date': _home_date(r['created_at'])}
               for r in cur.fetchall()]

    cur.close()
    conn.close()

    data = {'success': True, 'teamcolor_date': tc_date, 'teamcolor_prev_date': tc_prev_date,
            'teamcolors': teamcolors, 'traits': traits, 'trait_dates': trait_dates,
            'community': community, 'reviews': reviews, 'updates': updates}
    _home_cache['data'], _home_cache['time'] = data, now
    return jsonify(data)


# 홈: 구단가치별 랭커 스쿼드 구간 (단위: BP / 1억 = 1e8, 1조 = 1e12)
HOME_SQUAD_BUCKETS = [
    (1e8, 5e8, '~5억'),
    (5e8, 10e8, '~10억'),
    (10e8, 30e8, '~30억'),
    (30e8, 50e8, '~50억'),
    (50e8, 100e8, '~100억'),
    (100e8, None, '100억+'),
]
HOME_SQUAD_MIN_BUILDUP = 8   # 이 강화 단계 미만 카드가 하나라도 있으면 홈에 표시하지 않음
_home_squad_cache = {'data': None, 'time': None}


@app.route('/api/home_squads')
def home_squads():
    """홈 화면: 구단가치 구간별 상위 랭커 스쿼드 10개 (10분간 재사용)"""
    now = datetime.now()
    if _home_squad_cache['data'] and (now - _home_squad_cache['time']).total_seconds() < 600:
        return jsonify(_home_squad_cache['data'])

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT crawl_date, squad_full_data, full_data->'_logos' AS logos
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': '데이터가 없습니다'}), 404

    squad_data = row['squad_full_data'] or {}
    if isinstance(squad_data, str):
        squad_data = json.loads(squad_data)
    logos = row['logos'] or {}

    # 팀컬러 구분 없이 전체 랭커를 순위순으로
    rankers = []
    for tc, lst in squad_data.items():
        for r in lst or []:
            rankers.append((r.get('rank') or 999999, tc, r))
    rankers.sort(key=lambda x: x[0])

    buckets = []
    for lo, hi, label in HOME_SQUAD_BUCKETS:
        picked = []
        for rank, tc, r in rankers:
            v = r.get('squad_value') or 0
            if v >= lo and (hi is None or v < hi):
                squad = r.get('squad', [])
                # 미완성 스쿼드 제외: 선수가 11명 미만이거나, 강화 단계가 기준 미만인 카드가 있으면 건너뜀
                if len(squad) < 11 or any((s.get('buildup') or 0) < HOME_SQUAD_MIN_BUILDUP for s in squad):
                    continue
                picked.append({
                    'rank': rank, 'nickname': r.get('nickname', ''),
                    'teamcolor': tc, 'logo': logos.get(tc, ''), 'value': v,
                    'squad': [{'p': s.get('position'), 'spid': s.get('spid'), 'b': s.get('buildup') or 0}
                              for s in r.get('squad', [])]
                })
                if len(picked) >= 20:
                    break
        buckets.append({'label': label, 'min': lo, 'max': hi, 'squads': picked})

    # 화면에 나오는 카드들의 시즌 이미지와 신규 특성
    spids = list({int(p['spid']) for b in buckets for s in b['squads'] for p in s['squad'] if p.get('spid')})
    season_imgs, card_traits, card_names = {}, {}, {}
    if spids:
        cur.execute("SELECT season_id, season_img_url FROM seasons")
        season_imgs = {str(r['season_id']): r['season_img_url'] for r in cur.fetchall()}

        cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new'")
        new_trait_names = set(r['trait_name'] for r in cur.fetchall())

        cur.execute(
            "SELECT spid, player_name, full_data->'game_info'->'traits' AS traits FROM player_cards WHERE spid = ANY(%s)",
            (spids,)
        )
        for r in cur.fetchall():
            card_names[str(r['spid'])] = (r['player_name'] or '').strip().split(' ')[-1]
            traits = r['traits'] or []
            found = next((t for t in traits if t in new_trait_names), None)
            if found:
                card_traits[str(r['spid'])] = found
    cur.close()
    conn.close()

    for b in buckets:
        for s in b['squads']:
            for p in s['squad']:
                sp = str(p.get('spid') or '')
                p['season'] = season_imgs.get(sp[:3], '')
                p['trait'] = card_traits.get(sp)
                p['name'] = card_names.get(sp, '')

    data = {'success': True,
            'date': f"{row['crawl_date'].month}월 {row['crawl_date'].day}일",
            'buckets': buckets}
    _home_squad_cache['data'], _home_squad_cache['time'] = data, now
    return jsonify(data)


# ── 커뮤니티 글 HTML 정화 ─────────────────────────────────────
# 에디터(Quill)가 만드는 태그만 허용하고, 스크립트·이벤트 속성·외부 iframe 등은 제거
ANON_NAME = '큐붕이'  # 비로그인 사용자 기본 이름
_ANON_ALIASES = {'', '익명', ANON_NAME}  # 예전 기본 이름 '익명'도 큐붕이로 취급


def is_anon_name(name):
    return (name or '').strip() in _ANON_ALIASES


@app.template_filter('display_author')
def display_author(name):
    """화면 표시용 이름: 예전 '익명'은 큐붕이로 보여줌 (DB는 그대로)"""
    return ANON_NAME if is_anon_name(name) else name


def _ip_prefix(ip):
    """IP 앞 두 자리 (예: 118.235.x.x -> 118.235). IPv6는 앞 두 블록"""
    if not ip:
        return None
    sep = ':' if ':' in ip else '.'
    parts = ip.split(sep)
    return sep.join(parts[:2]) if len(parts) >= 2 else ip


def _anon_op_match(post_ip, post_pw_hash, c_ip, c_pw_hash):
    """비회원 글쓴이 판단 (IP·비밀번호 기준)
    - 같은 IP이거나
    - 비밀번호가 같고 IP 앞 두 자리도 같음 (휴대폰 데이터처럼 IP 뒷자리만 바뀐 경우)
    ※ 비밀번호만 같은 경우는 인정하지 않음 (1234 같은 흔한 비밀번호가 겹쳐 남이 글쓴이로 표시되는 문제)
    """
    if c_ip and post_ip and c_ip == post_ip:
        return True
    same_pw = bool(c_pw_hash) and c_pw_hash == post_pw_hash
    return same_pw and _ip_prefix(c_ip) is not None and _ip_prefix(c_ip) == _ip_prefix(post_ip)


def _is_anon_op(post, c):
    """비회원 글의 글쓴이 댓글인지
    1) 댓글 작성 시 같은 브라우저로 확인해서 저장한 값 (comments.is_op)
    2) 같은 IP, 또는 같은 비밀번호 + IP 앞 두 자리
    """
    if c.get('user_id'):
        return False
    if c.get('is_op'):
        return True
    return _anon_op_match(post.get('author_ip'), post.get('password_hash'),
                          c.get('author_ip'), c.get('password_hash'))


def label_comment_authors(post, comments):
    """댓글 작성자 표시 정리
    - 글쓴이 본인 댓글: is_op=True (회원 글은 회원 ID, 비회원 글은 같은 브라우저/같은 IP/같은 비밀번호+IP 앞 두 자리)
    - 기본 이름(큐붕이/익명) 비회원: 글 안에서 처음 댓글 단 순서대로 큐붕이1, 큐붕이2 ... (같은 IP는 같은 번호)
    - 번호는 삭제된 댓글까지 포함해 매겨서, 삭제돼도 다른 사람 번호가 바뀌지 않음
    """
    numbers = {}
    for c in sorted(comments, key=lambda x: (x.get('created_at') is None, x.get('created_at'), x.get('id'))):
        if post.get('user_id'):
            c['is_op'] = bool(c.get('user_id')) and c.get('user_id') == post.get('user_id')
        else:
            c['is_op'] = _is_anon_op(post, c)

        if not c.get('user_id') and is_anon_name(c.get('author')) and not c['is_op']:
            key = c.get('author_ip') or c.get('ip_hash') or f"c{c.get('id')}"
            if key not in numbers:
                numbers[key] = len(numbers) + 1
            c['display_name'] = f'{ANON_NAME}{numbers[key]}'
        else:
            c['display_name'] = display_author(c.get('author'))
COMMUNITY_CATEGORIES = ['잡담', '꿀팁', '스쿼드', '선수 후기', '전술', '강화/득템', '감독모드', '미니 페이스온', '명장면']
_POST_ALLOWED_TAGS = {'p', 'br', 'span', 'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del',
                      'h1', 'h2', 'h3', 'blockquote', 'pre', 'code', 'ol', 'ul', 'li',
                      'a', 'img', 'iframe'}
_POST_ALLOWED_ATTRS = {
    '*': {'class', 'style'},
    'a': {'href', 'target'},
    'img': {'src', 'alt', 'width', 'height'},
    'iframe': {'src', 'frameborder', 'allowfullscreen', 'width', 'height'},
    'li': {'data-list'},
    'pre': {'spellcheck'},
}
_POST_VIDEO_SRC = re.compile(r'^https://(www\.)?(youtube\.com|youtube-nocookie\.com)/embed/[\w\-]+')


def _post_attr_filter(tag, attr, value):
    if tag == 'iframe' and attr == 'src':
        return value if _POST_VIDEO_SRC.match(value) else None  # 유튜브 영상만 허용
    if tag == 'img' and attr == 'src':
        return value if value.startswith(('https://', 'http://', 'data:image/')) else None
    if tag == 'a' and attr == 'href':
        return value if value.startswith(('https://', 'http://', '/')) else None
    if attr == 'class':
        kept = [c for c in value.split() if c.startswith('ql-')]  # 에디터 정렬/들여쓰기 클래스만
        return ' '.join(kept) or None
    return value


def clean_post_html(html):
    """커뮤니티 글 본문에서 허용된 HTML만 남김 (저장 시 + 표시 시 모두 사용)"""
    if not html:
        return ''
    return nh3.clean(html, tags=_POST_ALLOWED_TAGS, attributes=_POST_ALLOWED_ATTRS,
                     attribute_filter=_post_attr_filter,
                     url_schemes={'http', 'https', 'data'},
                     filter_style_properties={'color', 'background-color'})


@app.route('/community')
def community_list():
    """커뮤니티 메인 - 게시글 목록"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        return _community_list(cur)
    finally:
        conn.close()


COMMUNITY_PER_PAGE = 20


def _board_params(args):
    """목록 상태(카테고리/인기글/검색/페이지)를 URL 파라미터에서 읽기"""
    return {
        'category': args.get('category', ''),
        'page': max(args.get('page', 1, type=int) or 1, 1),
        'search_type': args.get('search_type', ''),
        'keyword': args.get('keyword', ''),
        'show_popular': args.get('popular', '') == 'true',
    }


def _board_conditions(bp, is_admin):
    """목록 조건(WHERE)과 파라미터 생성"""
    params = []
    conditions = []

    # 카테고리 필터
    if bp['category']:
        conditions.append("category = %s")
        params.append(bp['category'])
    else:
        # 전체글·인기글·전체 검색에서는 관리자 업데이트 글 제외 (업데이트 탭에서만 보이게)
        conditions.append("COALESCE(category, '') <> '업데이트'")

    # 인기글 필터
    if bp['show_popular']:
        conditions.append("is_popular = true")

    # 검색 조건 (띄어쓰기 무시, 여러 단어는 모두 포함)
    keyword, search_type = bp['keyword'], bp['search_type']
    if keyword and search_type:
        columns = {
            'title': ["REPLACE(title, ' ', '')"],
            'content': ["REPLACE(content, ' ', '')"],
            'title_content': ["REPLACE(title, ' ', '')", "REPLACE(content, ' ', '')"],
            'author': ["REPLACE(author, ' ', '')"],
        }
        search_conditions = []
        for kw in keyword.split():
            like = f'%{kw}%'
            if search_type == 'comment':
                search_conditions.append("""id IN (SELECT post_id FROM community.comments
                                               WHERE REPLACE(content, ' ', '') ILIKE %s)""")
                params.append(like)
            elif search_type == 'author' and is_anon_name(kw):
                search_conditions.append("REPLACE(author, ' ', '') IN ('익명', %s)")
                params.append(ANON_NAME)
            elif search_type in columns:
                cols = columns[search_type]
                search_conditions.append('(' + ' OR '.join(f'{c} ILIKE %s' for c in cols) + ')')
                params.extend([like] * len(cols))
        if search_conditions:
            conditions.append(f"({' AND '.join(search_conditions)})")

    # 일반 사용자는 삭제되지 않은 글만 보기
    if not is_admin:
        conditions.append("is_deleted = false")

    # 공지는 목록 위 '접는 공지 띠'로 따로 보여주므로 일반 목록에서는 제외
    conditions.append("COALESCE(is_notice, false) = false")

    return conditions, params


def _board_qs(bp, page=None):
    """글 링크/페이지 링크에 붙일 목록 상태 쿼리스트링"""
    q = {}
    if bp['show_popular']:
        q['popular'] = 'true'
    if bp['category']:
        q['category'] = bp['category']
    if bp['keyword'] and bp['search_type']:
        q['search_type'] = bp['search_type']
        q['keyword'] = bp['keyword']
    page = page if page is not None else bp['page']
    if page and page > 1:
        q['page'] = page
    return urllib.parse.urlencode(q)


def build_board(cur, args, anchor_post=None, with_notices=True):
    """커뮤니티 목록 데이터 (목록 화면 + 글 아래 목록 공용)
    anchor_post: 글 상세에서 page 파라미터가 없으면 그 글이 들어 있는 페이지를 찾아서 보여줌
    """
    bp = _board_params(args)
    is_admin = session.get('user_role') == 'admin'
    conditions, params = _board_conditions(bp, is_admin)
    where = " WHERE " + " AND ".join(conditions)

    # 전체 글 수
    cur.execute("SELECT COUNT(*) FROM community.posts" + where, params)
    total_count = cur.fetchone()['count']
    total_pages = max((total_count + COMMUNITY_PER_PAGE - 1) // COMMUNITY_PER_PAGE, 1)

    # 글 상세에서 page가 따로 없으면: 현재 글보다 최신 글 수로 페이지 계산
    if anchor_post is not None and 'page' not in args and anchor_post.get('created_at'):
        cur.execute("SELECT COUNT(*) FROM community.posts" + where + " AND created_at > %s",
                    params + [anchor_post['created_at']])
        newer = cur.fetchone()['count']
        bp['page'] = newer // COMMUNITY_PER_PAGE + 1

    bp['page'] = min(bp['page'], total_pages)

    # 목록 (본문 전체는 가져오지 않음: 사진이 본문에 들어 있어 글당 수백 KB)
    cur.execute("""
        SELECT id, category, title, author, author_ip, created_at, views, likes,
               is_notice, is_deleted,
               (POSITION('<img' IN content) > 0) AS has_image,
               (POSITION('<iframe' IN content) > 0
                OR POSITION('youtube.com' IN content) > 0
                OR POSITION('youtu.be' IN content) > 0) AS has_video,
               (SELECT COUNT(*) FROM community.comments c
                WHERE c.post_id = community.posts.id AND c.is_deleted = false) AS comment_count
        FROM community.posts""" + where + """
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, params + [COMMUNITY_PER_PAGE, (bp['page'] - 1) * COMMUNITY_PER_PAGE])
    posts = cur.fetchall()

    for p in posts:
        p['display_date'] = format_post_time(p['created_at'])
        p['ip_display'] = format_ip_display(p.get('author_ip'))

    # 공지 목록 (검색 중이 아닐 때만, 최신순, 가벼운 컬럼만)
    notices = []
    if with_notices and not bp['keyword']:
        cur.execute("""
            SELECT id, title, created_at FROM community.posts
            WHERE is_notice = true AND is_deleted = false
            ORDER BY created_at DESC
            LIMIT 10
        """)
        notices = cur.fetchall()

    return {
        'posts': posts,
        'notices': notices,
        'current_page': bp['page'],
        'total_pages': total_pages,
        'category': bp['category'],
        'search_type': bp['search_type'],
        'keyword': bp['keyword'],
        'show_popular': bp['show_popular'],
        'board_qs': _board_qs(bp),
        'page_qs': _board_qs(bp, page=0),   # 페이지 번호 링크용 (page 제외)
    }


def _community_list(cur):
    board = build_board(cur, request.args)
    return render_template('community.html', current_post_id=None, **board)


@app.route('/community/write', methods=['GET', 'POST'])
def community_write():
    """글쓰기"""
    if request.method == 'POST':
        if 'user_id' not in session:
             author_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
             conn = get_db_connection()
             cur = conn.cursor()
             cur.execute("SELECT 1 FROM community.banned_ips WHERE ip = %s", (author_ip,))
             if cur.fetchone():
                 cur.close()
                 conn.close()
                 return redirect('/community')
             cur.close()
             conn.close()
        category = request.form.get('category')
        is_admin = session.get('user_role') == 'admin'
        if category not in COMMUNITY_CATEGORIES and not (category == '업데이트' and is_admin):
            return redirect('/community')
        title = (request.form.get('title') or '').strip()[:200]
        content = clean_post_html(request.form.get('content') or '')  # 허용된 HTML만 저장
        if not title or not content.strip():
            return redirect('/community/write')

        # 로그인 여부 확인
        if 'user_id' in session:
            # 로그인 상태: 세션 정보 사용
            author = session.get('user_name', '익명')
            author_ip = None  # 로그인 유저는 IP 저장 안 함
            password_hash = None  # 로그인 유저는 비밀번호 불필요
            user_id = session.get('user_id')  # 작성자 ID 저장
        else:
            # 비로그인 상태: 폼 데이터 사용
            author = (request.form.get('author') or '').strip()[:100] or ANON_NAME
            password = request.form.get('password', '')
            author_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
            password_hash = hash_password(password) if password else None
            user_id = None
        
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO community.posts (category, title, content, author, author_ip, password_hash, user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (category, title, content, author, author_ip,  password_hash, user_id, datetime.now(pytz.UTC)))
            new_id = cur.fetchone()['id']
            conn.commit()

            # 비회원: 이 브라우저에 '내가 쓴 글' 기록 (댓글 달 때 글쓴이 표시용, 최근 50개)
            if not user_id:
                my_posts = [pid for pid in session.get('my_posts', []) if pid != new_id]
                session['my_posts'] = (my_posts + [new_id])[-50:]
                session.permanent = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return redirect('/community')
    
    return render_template('community_write.html')


def _should_count_view(post_id):
    """최근 본 글 목록(세션)에 없거나 6시간이 지났으면 True"""
    now = int(datetime.now(pytz.UTC).timestamp())
    viewed = session.get('viewed_posts', {})
    key = str(post_id)
    if now - viewed.get(key, 0) < 6 * 3600:
        return False
    viewed[key] = now
    # 쿠키 용량 보호: 최근 30개만 유지
    if len(viewed) > 30:
        viewed = dict(sorted(viewed.items(), key=lambda x: x[1])[-30:])
    session['viewed_posts'] = viewed
    return True


@app.route('/community/post/<int:post_id>')
def community_post(post_id):
    """게시글 상세보기"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        return _community_post(conn, cur, post_id)
    finally:
        conn.close()


def _community_post(conn, cur, post_id):
    # 조회수 증가 (같은 브라우저는 6시간에 한 번만 집계)
    if _should_count_view(post_id):
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
            ORDER BY parent_comment_id NULLS FIRST, created_at ASC
        """, (post_id,))
    else:
        cur.execute("""
            SELECT * FROM community.comments 
            WHERE post_id = %s AND is_deleted = false
            ORDER BY parent_comment_id NULLS FIRST, created_at ASC
        """, (post_id,))    
    comments = cur.fetchall()
    # 댓글 시간 UTC → KST 변환
    kst = pytz.timezone('Asia/Seoul')
    for comment in comments:
        if comment['created_at']:
            utc_time = comment['created_at'].replace(tzinfo=pytz.UTC)
            comment['created_at'] = utc_time.astimezone(kst)    
    
    for comment in comments:
        comment['ip_display'] = format_ip_display(comment.get('author_ip'))

    # 큐붕이 번호 / 글쓴이 표시
    label_comment_authors(post, comments)
    
    # 본문 정화 (예전 글 포함, 허용된 HTML만 출력)
    post['content'] = clean_post_html(post.get('content'))

    # 검색엔진/공유 미리보기용 요약 (태그 제거한 본문 앞부분)
    plain = re.sub(r'<[^>]+>', ' ', post['content'])
    plain = re.sub(r'\s+', ' ', plain).strip()
    post['summary'] = (plain[:120] + '…') if len(plain) > 120 else (plain or post['title'])

    # 수정/삭제 버튼 노출: 관리자, 비로그인 글(비밀번호로 확인), 로그인 글은 작성자 본인만
    post['can_manage'] = (is_admin or not post.get('user_id')
                          or session.get('user_id') == post.get('user_id'))

    # 글 아래 목록 (보던 목록 그대로, 현재 글이 들어 있는 페이지)
    board = build_board(cur, request.args, anchor_post=post, with_notices=False)

    return render_template('community_post.html',
                         post=post,
                         comments=comments,
                         current_post_id=post['id'],
                         **board)


@app.route('/community/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    """댓글 추가 (로그인/비로그인 모두 가능)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        content = request.form.get('content', '').strip()
        parent_comment_id = request.form.get('parent_comment_id') or None  # 대댓글인 경우
        
        if not content:
            return jsonify({'success': False, 'message': '내용을 입력해주세요'}), 400
        
        # 로그인 여부 확인
        if 'user_id' in session:
            # 로그인 유저
            author = session.get('user_name', '회원')
            user_id = session.get('user_id')
            password_hash = None
            ip_hash = None
            author_ip = None
        else:
            # 비로그인 유저
            author = (request.form.get('author') or '').strip()[:100] or ANON_NAME
            password = request.form.get('password', '').strip()
            
            if not password:
                return jsonify({'success': False, 'message': '비밀번호를 입력해주세요'}), 400
            
            user_id = None
            password_hash = hash_password(password)
            ip_hash = hash_ip(request.remote_addr)
            author_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        
        # 글쓴이 댓글인지 판단 (회원: 회원 ID / 비회원: 같은 브라우저·같은 IP·같은 비밀번호+IP 앞 두 자리)
        cur.execute("SELECT user_id, author_ip, password_hash FROM community.posts WHERE id = %s", (post_id,))
        target = cur.fetchone()
        if not target:
            return "게시글을 찾을 수 없습니다", 404
        if user_id:
            is_op = bool(target['user_id']) and target['user_id'] == user_id
        elif target['user_id']:
            is_op = False
        else:
            is_op = (post_id in session.get('my_posts', [])
                     or _anon_op_match(target['author_ip'], target['password_hash'], author_ip, password_hash))

        # 댓글 삽입
        cur.execute("""
            INSERT INTO community.comments 
            (post_id, author, content, user_id, password_hash, ip_hash, author_ip, parent_comment_id, created_at, is_op)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (post_id, author, content, user_id, password_hash, ip_hash, author_ip, parent_comment_id, datetime.now(pytz.UTC), is_op))
        
        conn.commit()
        return redirect(url_for('community_post', post_id=post_id))
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'댓글 작성 중 오류 발생: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/community/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    """게시글 삭제 (Soft Delete)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 게시글 조회
        cur.execute("SELECT password_hash, user_id FROM community.posts WHERE id = %s", (post_id,))
        post = cur.fetchone()
        
        if not post:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '게시글을 찾을 수 없습니다'}), 404
        
        # 권한 확인
        deleted_by = None
        if post['user_id']:
            # 로그인 유저가 작성한 글: 세션 user_id 확인
            if 'user_id' not in session or session['user_id'] != post['user_id']:
                cur.close()
                conn.close()
                return jsonify({'success': False, 'message': '본인이 작성한 글만 삭제할 수 있습니다'}), 403
            deleted_by = session.get('user_id')
        else:
            # 비로그인 유저가 작성한 글: 비밀번호 확인
            password = request.form.get('password', '')
            if not verify_password(password, post['password_hash']):
                cur.close()
                conn.close()
                return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다'}), 403
        
        # Soft Delete: is_deleted를 true로 설정
        cur.execute("""
            UPDATE community.posts 
            SET is_deleted = true, 
                deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s
            WHERE id = %s
        """, (deleted_by, post_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': '게시글이 삭제되었습니다'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'삭제 중 오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()
        
@app.route('/community/post/<int:post_id>/toggle_notice', methods=['POST'])
@admin_required
def toggle_notice(post_id):
    """관리자 전용: 공지글 고정/해제"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 게시글 조회
        cur.execute("SELECT is_notice, user_id FROM community.posts WHERE id = %s", (post_id,))
        post = cur.fetchone()
        
        if not post:
            return jsonify({'success': False, 'message': '게시글을 찾을 수 없습니다'}), 404
        
        # 관리자가 작성한 글만 공지로 설정 가능
        if post['user_id'] != session.get('user_id'):
            return jsonify({'success': False, 'message': '본인이 작성한 글만 공지로 설정할 수 있습니다'}), 403
        
        # is_notice 토글
        new_notice_status = not post['is_notice']
        cur.execute("""
            UPDATE community.posts 
            SET is_notice = %s 
            WHERE id = %s
        """, (new_notice_status, post_id))
        
        conn.commit()
        
        message = '공지글로 고정되었습니다' if new_notice_status else '공지글 고정이 해제되었습니다'
        return jsonify({'success': True, 'message': message, 'is_notice': new_notice_status})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()        


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
    """댓글 삭제 (Soft Delete)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 댓글 조회
        cur.execute("SELECT password_hash, post_id, user_id FROM community.comments WHERE id = %s", (comment_id,))
        comment = cur.fetchone()
        
        if not comment:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '댓글을 찾을 수 없습니다'}), 404
        
        # 권한 확인
        deleted_by = None
        if comment['user_id']:
            # 로그인 유저가 작성한 댓글: 세션 user_id 확인
            if 'user_id' not in session or session['user_id'] != comment['user_id']:
                cur.close()
                conn.close()
                return jsonify({'success': False, 'message': '본인이 작성한 댓글만 삭제할 수 있습니다'}), 403
            deleted_by = session.get('user_id')
        else:
            # 비로그인 유저가 작성한 댓글: 비밀번호 확인
            password = request.form.get('password', '')
            if not verify_password(password, comment['password_hash']):
                cur.close()
                conn.close()
                return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다'}), 403
        
        # Soft Delete: is_deleted를 true로 설정
        cur.execute("""
            UPDATE community.comments 
            SET is_deleted = true, 
                deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s
            WHERE id = %s
        """, (deleted_by, comment_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': '댓글이 삭제되었습니다', 'post_id': comment['post_id']})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'삭제 중 오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/community/post/<int:post_id>/edit')
def edit_post_page(post_id):
    """게시글 수정 페이지"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 게시글 조회
    cur.execute("SELECT * FROM community.posts WHERE id = %s", (post_id,))
    post = cur.fetchone()
    
    if not post:
        cur.close()
        conn.close()
        return redirect('/community')
    
    # 권한 확인
    if post['user_id']:
        # 로그인 유저가 작성한 글: 세션 user_id 확인
        if 'user_id' not in session or session['user_id'] != post['user_id']:
            cur.close()
            conn.close()
            alert_message = "본인이 작성한 글만 수정할 수 있습니다"
            return f"<script>alert('{alert_message}'); window.location='/community/post/{post_id}';</script>"
    else:
        # 비로그인 유저가 작성한 글: 비밀번호 확인을 통과했는지 세션으로 확인
        if session.get('edit_auth') != post_id:
            cur.close()
            conn.close()
            return redirect(f'/community/post/{post_id}')
    
    cur.close()
    conn.close()
    
    post['content'] = clean_post_html(post.get('content'))  # 에디터에 넣기 전 정화
    return render_template('community_edit.html', post=post)


@app.route('/community/post/<int:post_id>/edit/auth', methods=['POST'])
def edit_post_auth(post_id):
    """비로그인 글 수정 전 비밀번호 확인 (비밀번호가 주소창에 남지 않도록 POST로 받음)"""
    password = request.form.get('password', '')
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT password_hash, user_id FROM community.posts WHERE id = %s", (post_id,))
        post = cur.fetchone()
    finally:
        conn.close()

    if post and not post['user_id'] and post['password_hash'] and verify_password(password, post['password_hash']):
        session['edit_auth'] = post_id
        return redirect(f'/community/post/{post_id}/edit')
    return """
        <script>
            alert('비밀번호가 일치하지 않습니다');
            window.location='/community/post/""" + str(post_id) + """';
        </script>
    """


@app.route('/community/post/<int:post_id>/edit', methods=['POST'])
def edit_post_submit(post_id):
    """게시글 수정 처리"""
    category = request.form.get('category')
    title = request.form.get('title')
    content = clean_post_html(request.form.get('content') or '')  # 허용된 HTML만 저장
    is_admin = session.get('user_role') == 'admin'
    if category not in COMMUNITY_CATEGORIES and not (category == '업데이트' and is_admin):
        return redirect(f'/community/post/{post_id}')
    title = (title or '').strip()[:200]
    if not title or not content.strip():
        return redirect(f'/community/post/{post_id}')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 게시글 조회
        cur.execute("SELECT password_hash, user_id FROM community.posts WHERE id = %s", (post_id,))
        post = cur.fetchone()
        
        if not post:
            cur.close()
            conn.close()
            return "게시글을 찾을 수 없습니다", 404
        
        # 권한 확인
        if post['user_id']:
            # 로그인 유저가 작성한 글: 세션 user_id 확인
            if 'user_id' not in session or session['user_id'] != post['user_id']:
                cur.close()
                conn.close()
                return """
                    <script>
                        alert('본인이 작성한 글만 수정할 수 있습니다');
                        window.location='/community/post/""" + str(post_id) + """';
                    </script>
                """
        else:
            # 비로그인 유저가 작성한 글: 비밀번호 확인 통과 여부(세션) 확인
            if session.get('edit_auth') != post_id:
                cur.close()
                conn.close()
                return """
                    <script>
                        alert('수정 권한이 만료되었습니다. 글에서 수정 버튼을 다시 눌러주세요');
                        window.location='/community/post/""" + str(post_id) + """';
                    </script>
                """
        
        # 게시글 수정
        cur.execute("""
            UPDATE community.posts 
            SET category = %s, title = %s, content = %s 
            WHERE id = %s
        """, (category, title, content, post_id))
        
        conn.commit()
        session.pop('edit_auth', None)  # 수정 완료 후 허가 해제
        return redirect(f'/community/post/{post_id}')
        
    except Exception as e:
        conn.rollback()
        return f"""
            <script>
                alert('수정 중 오류가 발생했습니다: {str(e)}');
                history.back();
            </script>
        """, 500
    finally:
        cur.close()
        conn.close()


@app.route('/search') 
def search():
    """1페이지: 검색 페이지"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # 모든 시즌 가져오기
        cur.execute("""
            SELECT season_id, season_name, season_img_url 
            FROM seasons
        """)
        all_seasons = cur.fetchall()
        
        seasons_dict = {s['season_id']: s for s in all_seasons}
        
        ordered_seasons = []
        for sid in SEASON_ORDER:
            if sid in seasons_dict:
                ordered_seasons.append(seasons_dict[sid])
        
        cur.execute("SELECT position FROM positions ORDER BY position")
        positions = [row['position'] for row in cur.fetchall()]
        
        cur.execute("""
            SELECT nation_name 
            FROM nation_teamcolors 
            ORDER BY nation_name COLLATE "C"
        """)
        nation_data = [row['nation_name'] for row in cur.fetchall()]
        nations_old = nation_data
        nation_teamcolors = nation_data
        
        cur.execute('SELECT club_name FROM club_teamcolors ORDER BY club_name COLLATE "C"')
        club_teamcolors = [row['club_name'] for row in cur.fetchall()]
        
        cur.execute('SELECT name FROM special_teamcolors ORDER BY name COLLATE "C"')
        trait_teamcolors = [row['name'] for row in cur.fetchall()]
        
        cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new' ORDER BY trait_name")
        new_traits = [row['trait_name'] for row in cur.fetchall()]
        
        cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'normal' ORDER BY trait_name")
        normal_traits = [row['trait_name'] for row in cur.fetchall()]
        
        cur.close()
    finally:
        conn.close()
    
    return render_template('search.html', 
                         seasons=ordered_seasons,
                         positions=positions,
                         nations=nations_old,
                         nation_teamcolors=nation_teamcolors,
                         club_teamcolors=club_teamcolors,
                         trait_teamcolors=trait_teamcolors,
                         new_traits=new_traits,
                         normal_traits=normal_traits)

@app.route('/api/search_results')
def api_search_results():
    """검색 결과 API (JSON 반환)"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        player_name_raw = request.args.get('player_name', '')
        player_names = [name.strip() for name in player_name_raw.split(',') if name.strip()]
        selected_seasons = request.args.getlist('seasons')
        selected_positions = request.args.getlist('positions')
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
        new_trait_list = [t for t in request.args.getlist('new_traits') if t]
        normal_trait_list = [t for t in request.args.getlist('normal_traits') if t]
        nation_team_color = request.args.get('nation_team_color', '')
        club_team_color_1 = request.args.get('club_team_color_1', '')
        club_team_color_2 = request.args.get('club_team_color_2', '')
        trait_team_color = request.args.get('trait_team_color', '')

        per_page = 200

        search_conditions, search_params = build_search_conditions(
            player_names, selected_seasons, selected_positions, min_ovr, max_ovr,
            min_salary, max_salary, preferred_foot, weak_foot_min, min_height, max_height,
            min_weight, max_weight, selected_body_types, [], nation_team_color,
            club_team_color_1, club_team_color_2, trait_team_color, False,
            new_trait_list, normal_trait_list
        )

        count_query = "SELECT COUNT(*) FROM player_cards WHERE 1=1" + search_conditions
        cur.execute(count_query, search_params)
        total_count = cur.fetchone()['count']
        
        teamcolor_info = None
        if trait_team_color:
            cur.execute(
                "SELECT name, min_count, stat1_name, stat1_value, stat2_name, stat2_value, "
                "stat3_name, stat3_value, stat4_name, stat4_value "
                "FROM teamcolor_effects WHERE name = %s AND type = '특성'",
                (trait_team_color,)
            )
            effect = cur.fetchone()
            if effect:
                stats = []
                for i in range(1, 5):
                    stat_name = effect[f'stat{i}_name']
                    stat_value = effect[f'stat{i}_value']
                    if stat_name and stat_value is not None:
                        stats.append({'name': stat_name, 'value': stat_value})
                teamcolor_info = {
                    'name': effect['name'],
                    'min_count': effect['min_count'],
                    'stats': stats
                }

        query = """
        SELECT spid, player_name, season_name, overall, position,
               COALESCE(full_data->'image_info'->>'mini_faceon', full_data->'image_info'->>'mini_faceon_high') as image,
               full_data->'image_info'->>'mini_faceon_high' as image_high,
               full_data->'image_info'->>'season_img' as season_img,
               full_data->'game_info'->>'salary' as salary,
               full_data->'basic_info'->>'nation' as nation,
               full_data->'stats_info'->'main_overall'->'preferred_positions' as preferred_positions,
               full_data->'game_info'->>'preferred_foot' as preferred_foot,
               full_data->'game_info'->>'weak_foot' as weak_foot,
               full_data->'basic_info'->>'height' as height,
               full_data->'basic_info'->>'weight' as weight,
               full_data->'basic_info'->>'body_type' as body_type,
               full_data->'game_info'->>'skill_moves' as skill_moves,
               full_data->'game_info'->'traits' as traits,
               boost_change
        FROM player_cards
        WHERE 1=1
        """ + search_conditions + """
        ORDER BY overall DESC, player_name
        LIMIT %s OFFSET %s
        """

        cur.execute(query, search_params + [per_page, 0])
        cards = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return jsonify({
        'total_count': total_count,
        'is_limited': total_count > per_page,
        'cards': [dict(c) for c in cards],
        'teamcolor_info': teamcolor_info
    })

    
    
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

    if len(cards) != 2:
        cur.close()
        conn.close()
        return "카드를 찾을 수 없습니다", 404

    cur.execute("SELECT full_data FROM card_price_history WHERE spid = %s", (spid1,))
    ph1_row = cur.fetchone()
    price_history1 = ph1_row['full_data'] if ph1_row else None

    cur.execute("SELECT full_data FROM card_price_history WHERE spid = %s", (spid2,))
    ph2_row = cur.fetchone()
    price_history2 = ph2_row['full_data'] if ph2_row else None

    cur.close()
    conn.close()

    name1 = cards[0]['player_name']
    name2 = cards[1]['player_name']
    season1 = cards[0]['season_name']
    season2 = cards[1]['season_name']
    og_title = f"FCOnQ : {season1} - {name1} VS {season2} - {name2}"
    og_description = f"{name1}과 {name2}의 능력치를 비교해보세요!"

    return render_template('compare.html', card1=cards[0], card2=cards[1],
                           price_history1=price_history1, price_history2=price_history2,
                           og_title=og_title, og_description=og_description)
    
    
@app.route('/card/<int:spid>')
def card_detail(spid):
    """3페이지: 카드 상세 정보"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
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
        
        # 가격 추세 데이터 조회
        cur.execute("""
            SELECT full_data FROM card_price_history WHERE spid = %s
        """, (spid,))
        price_history = cur.fetchone()
        price_history_data = price_history['full_data'] if price_history else None
                # 해당 선수가 속한 특성 팀컬러 (선수 기준 = spid 뒤 6자리)
        cur.execute("""
            SELECT DISTINCT sc.name, te.image_url, te.min_count,
                   te.stat1_name, te.stat1_value, te.stat2_name, te.stat2_value,
                   te.stat3_name, te.stat3_value, te.stat4_name, te.stat4_value
            FROM special_teamcolor_players scp
            JOIN special_teamcolors sc ON scp.teamcolor_id = sc.id
            LEFT JOIN teamcolor_effects te ON te.name = sc.name AND te.type = '특성'
            WHERE scp.player_id = %s
            ORDER BY sc.name
        """, (str(spid)[-6:],))
        trait_teamcolors = []
        for r in cur.fetchall():
            groups = []  # 같은 수치 스탯끼리 묶기
            for i in range(1, 5):
                n, v = r[f'stat{i}_name'], r[f'stat{i}_value']
                if n and v is not None:
                    g = next((g for g in groups if g['value'] == v), None)
                    if g:
                        g['names'].append(n)
                    else:
                        groups.append({'value': v, 'names': [n]})
            trait_teamcolors.append({
                'name': r['name'], 'image_url': r['image_url'],
                'min_count': r['min_count'], 'stats': groups
            })
            
# 선수 후기 (카드 상세 '선수 후기' 탭용)
        if session.get('user_role') == 'admin':
            cur.execute("""
                SELECT * FROM player_reviews
                WHERE spid = %s
                ORDER BY parent_comment_id NULLS FIRST, created_at DESC
            """, (spid,))
        else:
            cur.execute("""
                SELECT * FROM player_reviews
                WHERE spid = %s AND is_deleted = false
                ORDER BY parent_comment_id NULLS FIRST, created_at DESC
            """, (spid,))
        reviews = cur.fetchall()
        kst = pytz.timezone('Asia/Seoul')
        for review in reviews:
            if review['created_at']:
                review['created_at'] = review['created_at'].replace(tzinfo=pytz.UTC).astimezone(kst)
            review['ip_display'] = format_ip_display(review.get('author_ip'))            
    finally:
        cur.close()
        conn.close()
    
    if not card:
        return "카드를 찾을 수 없습니다", 404
    
    player_name = card['player_name'] if card else '선수'
    season_name = card['season_name'] if card else ''
    position = card['stats_info']['main_overall']['card_position'] if card else ''
    og_title = f"FCOnQ : {season_name} - {player_name}"
    og_description = f"{player_name}의 능력치와 시세를 확인해보세요!"    
    
    return render_template('card_detail.html', card=card, 
                                               position_order=POSITION_ORDER,
                                               summary_order=SUMMARY_ORDER,
                                               detailed_order=DETAILED_ORDER,
                                               price_history=price_history_data,
                                               trait_teamcolors=trait_teamcolors,
                                               reviews=reviews,
                                               og_title=og_title,
                                               og_description=og_description)

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
    """(통합) 예전 선수 후기 주소 → 카드 상세 '선수 후기' 탭으로 이동"""
    return redirect(url_for('card_detail', spid=spid) + '#review', code=301)


@app.route('/player_review/<spid>/write', methods=['POST'])
def write_player_review(spid):
    """선수 후기 작성 (로그인/비로그인)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        content = request.form.get('content', '').strip()
        rating = request.form.get('rating')
        rating = int(rating) if rating else None
        parent_comment_id = request.form.get('parent_comment_id') or None
        
        if not content:
            return jsonify({'success': False, 'message': '내용을 입력해주세요'}), 400
        
        # 로그인 여부 확인
        if 'user_id' in session:
            author = session.get('user_name', '회원')
            user_id = session.get('user_id')
            password_hash = None
            ip_hash = None
            author_ip = None
        else:
            author = (request.form.get('author') or '').strip()[:100] or ANON_NAME
            password = request.form.get('password', '').strip()
            
            if not password:
                return jsonify({'success': False, 'message': '비밀번호를 입력해주세요'}), 400
            
            user_id = None
            password_hash = hash_password(password)
            ip_hash = hash_ip(request.remote_addr)
            author_ip = request.remote_addr
        
        # 후기 삽입
        cur.execute("""
            INSERT INTO player_reviews 
            (spid, author, content, rating, user_id, password_hash, ip_hash, author_ip, parent_comment_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (spid, author, content, rating, user_id, password_hash, ip_hash, author_ip, parent_comment_id, datetime.now(pytz.UTC)))
        
        conn.commit()
        return redirect(url_for('card_detail', spid=spid) + '#review')
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'작성 중 오류: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()


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
    """선수 후기 삭제 (Soft Delete)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 후기 조회
        cur.execute("SELECT password_hash, spid, user_id FROM player_reviews WHERE id = %s", (review_id,))
        review = cur.fetchone()
        
        if not review:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': '후기를 찾을 수 없습니다'}), 404
        
        # 권한 확인
        deleted_by = None
        if review['user_id']:
            # 로그인 유저가 작성한 후기: 세션 user_id 확인
            if 'user_id' not in session or session['user_id'] != review['user_id']:
                cur.close()
                conn.close()
                return jsonify({'success': False, 'message': '본인이 작성한 후기만 삭제할 수 있습니다'}), 403
            deleted_by = session.get('user_id')
        else:
            # 비로그인 유저가 작성한 후기: 비밀번호 확인
            password = request.form.get('password', '')
            if not verify_password(password, review['password_hash']):
                cur.close()
                conn.close()
                return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다'}), 403
        
        # Soft Delete: is_deleted를 true로 설정
        cur.execute("""
            UPDATE player_reviews 
            SET is_deleted = true, 
                deleted_at = CURRENT_TIMESTAMP,
                deleted_by = %s
            WHERE id = %s
        """, (deleted_by, review_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': '후기가 삭제되었습니다', 'spid': review['spid']})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'삭제 중 오류가 발생했습니다: {str(e)}'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/player_review/vote/<int:review_id>/<vote_type>', methods=['POST'])
def vote_player_review(review_id, vote_type):
    """선수 후기 추천/비추천"""
    if vote_type not in ['like', 'dislike']:
        return jsonify({'success': False, 'message': '잘못된 요청입니다'}), 400
    
    # IP 해시 생성
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    ip_hash = hash_ip(ip)
    
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
    

@app.route('/api/player_names')
def get_player_names():
    """선수 이름 리스트 반환 (자동완성용, 시즌 개수 포함)"""
    term = request.args.get('q', '')  # 검색어 파라미터
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT player_name, COUNT(*) AS card_count
        FROM player_cards
        WHERE player_name ILIKE %s
        GROUP BY player_name
        ORDER BY card_count DESC, player_name
        LIMIT 1000
    """, (f"%{term}%",))
    
    players = [{"name": row['player_name'], "count": row['card_count']} for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return jsonify(players)


@app.route('/tierlist')
def tierlist():
    """팀컬러 티어리스트 페이지"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 사용 가능한 날짜 목록 가져오기 (최신순)
    cur.execute("""
        SELECT crawl_date 
        FROM team_rankings 
        ORDER BY crawl_date DESC
    """)
    available_dates = [row['crawl_date'].strftime('%Y-%m-%d') for row in cur.fetchall()]
    
    # 팀 로고 데이터 가져오기
    cur.execute("""
        SELECT team_name, logo_url 
        FROM team_logos 
        ORDER BY team_name
    """)
    team_logos = {row['team_name']: row['logo_url'] for row in cur.fetchall()}
    
    # 포메이션 로고 데이터 가져오기
    cur.execute("""
        SELECT formation_name, logo_url 
        FROM formation_logos 
        ORDER BY formation_name
    """)
    formation_logos = {row['formation_name']: row['logo_url'] for row in cur.fetchall()}
    
    cur.execute("""
        SELECT season_id, season_img_url 
        FROM seasons
    """)
    season_logos = {str(row['season_id']): row['season_img_url'] for row in cur.fetchall()}
    
    cur.close()
    conn.close()
    
    tc_param = request.args.get('tc', '')
    tab_param = request.args.get('tab', '')

    if tab_param == 'card' and tc_param:
        og_title = f"FCOnQ - {tc_param} 선수 티어리스트"
        og_description = f"{tc_param} 팀컬러 포지션별 추천 선수를 확인해보세요!"
    else:
        og_title = "FCOnQ - FC온라인 전문 선수 DB 및 커뮤니티"
        og_description = "8만개 이상의 선수 카드 정보와 시세를 확인하고, FC온라인 유저들과 소통하세요!"
    
    return render_template('tierlist.html', 
                         available_dates=available_dates,
                         team_logos=team_logos,
                         formation_logos=formation_logos,
                         season_logos=season_logos,
                         og_title=og_title,
                         og_description=og_description)


@app.route('/utility')
def utility():
    """유틸리티 모음 페이지 (미페 검색기, 수수료 계산기 등)"""
    return render_template('utility.html')

@app.route('/fee_calculator')
def fee_calculator():
    """수수료 계산기 페이지"""
    return render_template('fee_calculator.html')

@app.route('/miniface_search')
def miniface_search():
    """미니 페이스온 검색기 페이지"""
    return render_template('miniface_search.html')

def get_nation_club_stages(cur, tc_name):
    cur.execute("SELECT stat1_name, stat2_name, image_url FROM teamcolor_effects WHERE name = %s", (tc_name,))
    row = cur.fetchone()

    if not row or (not row['stat1_name'] and not row['stat2_name']):
        return {'image_url': row['image_url'] if row else None, 'stages': None}

    s1, s2 = row['stat1_name'], row['stat2_name']
    stages = [
        {'stage': 1, 'min_count': 3, 'items': ['전체능력치 +1']},
        {'stage': 2, 'min_count': 6, 'items': ['전체능력치 +3']},
        {'stage': 3, 'min_count': 8, 'items': ['전체능력치 +3', f'{s1} +2', f'{s2} +1']},
        {'stage': 4, 'min_count': 11, 'items': ['전체능력치 +4', f'{s1} +3', f'{s2} +3']},
    ]
    return {'image_url': row['image_url'], 'stages': stages}


def get_trait_teamcolor_detail(cur, tc_name):
    cur.execute("SELECT id FROM special_teamcolors WHERE name = %s", (tc_name,))
    tc_row = cur.fetchone()

    if not tc_row:
        return {'image_url': None, 'min_count': None, 'stats': [], 'players': []}

    teamcolor_id = tc_row['id']

    cur.execute("""
        SELECT min_count, image_url, stat1_name, stat1_value, stat2_name, stat2_value,
               stat3_name, stat3_value, stat4_name, stat4_value
        FROM teamcolor_effects WHERE name = %s AND type = '특성'
    """, (tc_name,))
    eff_row = cur.fetchone()

    stats = []
    min_count = None
    image_url = None
    if eff_row:
        min_count = eff_row['min_count']
        image_url = eff_row['image_url']
        for i in range(1, 5):
            sname = eff_row[f'stat{i}_name']
            sval = eff_row[f'stat{i}_value']
            if sname and sval is not None:
                stats.append({'name': sname, 'value': sval})

    cur.execute("""
        SELECT pc.spid, pc.player_name, pc.position,
               pc.full_data->'game_info' AS game_info
        FROM player_cards pc
        WHERE RIGHT(pc.spid::text, 6) IN (
            SELECT player_id FROM special_teamcolor_players WHERE teamcolor_id = %s
        )
        ORDER BY pc.player_name, array_position(%s::integer[], CAST(LEFT(pc.spid::text, 3) AS INTEGER))
    """, (teamcolor_id, SEASON_ORDER))
    cards = cur.fetchall()

    cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new'")
    new_trait_names = set(row['trait_name'] for row in cur.fetchall())

    players = {}
    for c in cards:
        pid = str(c['spid'])[-6:]
        if pid not in players:
            players[pid] = {'pid': pid, 'name': c['player_name'], 'cards': []}
        game_info = c['game_info'] or {}
        traits = game_info.get('traits', [])
        new_trait = next((t for t in traits if t in new_trait_names), None)
        players[pid]['cards'].append({
            'spid': c['spid'],
            'salary': game_info.get('salary', ''),
            'new_trait': new_trait,
            'position': c['position']
        })

    return {
        'image_url': image_url,
        'min_count': min_count,
        'stats': stats,
        'players': list(players.values())
    }

@app.route('/api/teamcolor_search_by_name')
def api_teamcolor_search_by_name():
    tc_type = request.args.get('type')
    tc_name = request.args.get('name', '').strip()

    if not tc_type or not tc_name:
        return jsonify({'success': False, 'message': '팀컬러를 선택해주세요'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()

        if tc_type in ('nation', 'club'):
            result = get_nation_club_stages(cur, tc_name)
            return jsonify({'success': True, 'type': tc_type, 'name': tc_name, **result})

        elif tc_type == 'trait':
            result = get_trait_teamcolor_detail(cur, tc_name)
            return jsonify({'success': True, 'type': 'trait', 'name': tc_name, **result})

        return jsonify({'success': False, 'message': '잘못된 요청입니다'}), 400

    finally:
        conn.close()
        
@app.route('/api/teamcolor_search_by_keyword')
def api_teamcolor_search_by_keyword():
    tc_type = request.args.get('type')
    keyword = request.args.get('keyword', '').strip()

    if not tc_type or not keyword:
        return jsonify({'success': False, 'message': '검색어를 입력해주세요'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()

        if tc_type == 'nation':
            cur.execute("""
                SELECT nation_name AS name FROM nation_teamcolors
                WHERE nation_name ILIKE %s
                ORDER BY nation_name COLLATE "C"
            """, (f'%{keyword}%',))
        elif tc_type == 'club':
            cur.execute("""
                SELECT club_name AS name FROM club_teamcolors
                WHERE club_name ILIKE %s
                ORDER BY club_name COLLATE "C"
            """, (f'%{keyword}%',))
        elif tc_type == 'trait':
            cur.execute("""
                SELECT name FROM special_teamcolors
                WHERE name ILIKE %s
                ORDER BY name COLLATE "C"
            """, (f'%{keyword}%',))
        else:
            return jsonify({'success': False, 'message': '잘못된 요청입니다'}), 400

        matched = cur.fetchall()

        results = []
        for row in matched:
            name = row['name']
            if tc_type == 'trait':
                detail = get_trait_teamcolor_detail(cur, name)
                results.append({'type': 'trait', 'name': name, **detail})
            else:
                detail = get_nation_club_stages(cur, name)
                results.append({'type': tc_type, 'name': name, **detail})

        return jsonify({'success': True, 'keyword': keyword, 'results': results})

    finally:
        conn.close()        
        
@app.route('/api/teamcolor_search_by_stat')
def api_teamcolor_search_by_stat():
    stat_list = [s.strip() for s in request.args.getlist('stat') if s.strip()]
    stat_list = list(dict.fromkeys(stat_list))  # 중복 제거, 순서 유지

    if not stat_list:
        return jsonify({'success': False, 'message': '능력치를 선택해주세요'}), 400

    conditions = []
    params = []
    for s in stat_list:
        stripped = s.replace(' ', '')
        conditions.append("""(
            REPLACE(stat1_name, ' ', '') = %s
            OR REPLACE(stat2_name, ' ', '') = %s
            OR REPLACE(stat3_name, ' ', '') = %s
            OR REPLACE(stat4_name, ' ', '') = %s
        )""")
        params.extend([stripped, stripped, stripped, stripped])

    where_clause = " AND ".join(conditions)

    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute(f"""
            SELECT DISTINCT type, name,
                   CASE WHEN type = '특성' THEN 1 ELSE 0 END AS type_order
            FROM teamcolor_effects
            WHERE {where_clause}
            ORDER BY type_order, name
        """, params)
        matched = cur.fetchall()

        results = []
        for row in matched:
            if row['type'] == '특성':
                detail = get_trait_teamcolor_detail(cur, row['name'])
                results.append({'type': 'trait', 'name': row['name'], **detail})
            else:
                detail = get_nation_club_stages(cur, row['name'])
                results.append({'type': 'nation_or_club', 'name': row['name'], **detail})

        return jsonify({'success': True, 'stats': stat_list, 'results': results})

    finally:
        conn.close()

@app.route('/teamcolor_search')
def teamcolor_search():
    """팀컬러 상세 검색 페이지"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute('SELECT nation_name FROM nation_teamcolors ORDER BY nation_name COLLATE "C"')
        nation_teamcolors = [row['nation_name'] for row in cur.fetchall()]

        cur.execute('SELECT club_name FROM club_teamcolors ORDER BY club_name COLLATE "C"')
        club_teamcolors = [row['club_name'] for row in cur.fetchall()]

        cur.execute('SELECT name FROM special_teamcolors ORDER BY name COLLATE "C"')
        trait_teamcolors = [row['name'] for row in cur.fetchall()]

        stat_names = STAT_NAMES

        cur.execute("SELECT season_id, season_img_url FROM seasons")
        season_logos = {str(row['season_id']): row['season_img_url'] for row in cur.fetchall()}

        cur.close()
    finally:
        conn.close()

    return render_template('teamcolor_search.html',
                            nation_teamcolors=nation_teamcolors,
                            club_teamcolors=club_teamcolors,
                            trait_teamcolors=trait_teamcolors,
                            stat_names=stat_names,
                            season_logos=season_logos)

@app.route('/api/card_hover/<int:spid>')
@app.route('/api/card_hover/<int:spid>')
def card_hover(spid):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                pc.full_data->'basic_info' as basic_info,
                pc.full_data->'game_info' as game_info,
                pc.full_data->'image_info' as image_info
            FROM player_cards pc
            WHERE pc.spid = %s
        """, (spid,))
        card = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not card:
        return jsonify({}), 404
    return jsonify({
        'name': card['basic_info']['name'],
        'height': str(card['basic_info'].get('height', '')).replace('cm', '').strip(),
        'weight': str(card['basic_info'].get('weight', '')).replace('kg', '').strip(),
        'body_type': card['basic_info'].get('body_type', ''),
        'salary': card['game_info'].get('salary', ''),
        'traits': card['game_info'].get('traits', []),
        'preferred_foot': card['game_info'].get('preferred_foot', ''),
        'weak_foot': card['game_info'].get('weak_foot', ''),
    })


@app.route('/api/search_miniface', methods=['POST'])
def search_miniface():
    """미페 검색 API"""
    try:
        data = request.get_json()
        player_name = data.get('player_name', '').strip()
        
        if not player_name:
            return jsonify({'success': False, 'message': '선수 이름을 입력해주세요'}), 400
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 선수 검색 (시즌 정보와 JOIN)
        query = """
            WITH player_counts AS (
                SELECT 
                    player_name,
                    COUNT(*) as card_count
                FROM public.player_cards
                WHERE player_name ILIKE %s
                GROUP BY player_name
            )
            SELECT 
                pc.spid,
                pc.player_name,
                pc.season_name,
                s.season_img_url,
                CAST(LEFT(pc.spid::text, 3) AS INTEGER) as season_id
            FROM public.player_cards pc
            LEFT JOIN public.seasons s 
                ON CAST(LEFT(pc.spid::text, 3) AS INTEGER) = s.season_id
            INNER JOIN player_counts pco
                ON pc.player_name = pco.player_name
            WHERE pc.player_name ILIKE %s
            ORDER BY 
                pco.card_count DESC, 
                pc.player_name,
                array_position(%s::integer[], CAST(LEFT(pc.spid::text, 3) AS INTEGER))
        """

        cur.execute(query, (f'%{player_name}%', f'%{player_name}%', SEASON_ORDER))        
        results = cur.fetchall()
        
        cur.close()
        conn.close()
        
        if not results:
            return jsonify({'success': False, 'message': '검색 결과가 없습니다'})
        
        # 결과 포맷팅 (딕셔너리 접근)
        cards = []
        for row in results:
            cards.append({
                'spid': row['spid'],
                'player_name': row['player_name'],
                'season_name': row['season_name'],
                'season_img_url': row['season_img_url'] if row['season_img_url'] else ''
            })
        
        return jsonify({'success': True, 'cards': cards})
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"검색 오류 상세: {error_detail}")
        return jsonify({'success': False, 'message': f'검색 중 오류가 발생했습니다: {str(e)}'}), 500


@app.route('/api/get_tierlist_data')
def get_tierlist_data():
    """특정 날짜의 티어리스트 데이터 반환"""
    date = request.args.get('date')
    
    if not date:
        return jsonify({'success': False, 'message': '날짜를 선택해주세요'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT full_data 
        FROM team_rankings 
        WHERE crawl_date = %s
    """, (date,))
    
    result = cur.fetchone()
    
    cur.close()
    conn.close()
    
    if not result:
        return jsonify({'success': False, 'message': '데이터가 없습니다'}), 404
    
    return jsonify({'success': True, 'data': result['full_data']})


@app.route('/api/get_all_tierlist_data')
def get_all_tierlist_data():
    """모든 날짜의 티어리스트 데이터 반환 (최근 15개)"""
    ranking = request.args.get('ranking', '10000')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 최근 10개 날짜 데이터 가져오기
    cur.execute("""
        SELECT crawl_date, full_data 
        FROM team_rankings 
        ORDER BY crawl_date DESC 
        LIMIT 10
    """)
    
    results = []
    for row in cur.fetchall():
        date = row['crawl_date'].strftime('%m-%d')  # MM-DD 형식
        full_data = row['full_data']
        
        # 해당 ranking_range 찾기
        for dataset in full_data:
            if dataset['ranking_range'] == f'1-{ranking}':
                results.append({
                    'date': date,
                    'teams': dataset['teams'][:30]  # 상위 20개만
                })
                break
    
    # 날짜순 정렬 (오래된 것부터)
    results.reverse()
    
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'data': results})

# 티어리스트 / 스쿼드 메이커 공통: 이 인원 미만 팀컬러는 제외
TIERLIST_MIN_USERS = 10
TIERLIST_EXCLUDE_TEAMCOLORS = {'단일 팀'}
@app.route('/api/get_card_tierlist_data')
def get_card_tierlist_data():
    """카드 티어리스트 데이터 반환 (가장 최근 날짜)"""
    include_hover = request.args.get('include_hover') == 'true'
    bucket = request.args.get('bucket', '').strip()   # 구단가치 구간 (없으면 전체)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT full_data, crawl_date
        FROM card_tierlist_rankings 
        ORDER BY crawl_date DESC, id DESC 
        LIMIT 1
    """)

    result = cur.fetchone()

    if not result:
        cur.close()
        conn.close()
        return jsonify({'success': False, 'message': '데이터가 없습니다'}), 404

    full_data = result['full_data']
    bucket_label = ''
    if bucket:
        cur.execute("SELECT label, full_data FROM card_tierlist_gd WHERE bucket = %s", (bucket,))
        gd = cur.fetchone()
        if gd:
            full_data = gd['full_data']
            bucket_label = gd['label']
        else:
            bucket = ''   # 없는 구간이면 전체로

    # ===== 티어리스트 노출 설정 =====
    MIN_USERS = TIERLIST_MIN_USERS # 이 인원 미만 팀컬러는 제외
    EXCLUDE_TEAMCOLORS = TIERLIST_EXCLUDE_TEAMCOLORS
    CARDS_PER_POSITION = 20        # 포지션별로 보낼 최대 카드 수

    usage = full_data.get('_usage') or {}
    order = full_data.get('_order') or [k for k in full_data.keys() if not k.startswith('_')]
    order = [tc for tc in order if tc not in EXCLUDE_TEAMCOLORS]
    if usage:
        order = [tc for tc in order if usage.get(tc, 0) >= MIN_USERS]

    trimmed = {
        '_order': order,
        '_usage': {tc: usage[tc] for tc in order if tc in usage},
        '_logos': {tc: url for tc, url in (full_data.get('_logos') or {}).items() if tc in order},
    }
    for tc in order:
        trimmed[tc] = {pos: cards[:CARDS_PER_POSITION] for pos, cards in (full_data.get(tc) or {}).items()}

    full_data = trimmed
    teamcolor_names = order
    
        # 7일 전 순위 (같은 기준으로 걸러서 비교, 그날 데이터가 없으면 그 이전 중 가장 가까운 날)
    cur.execute("""
        SELECT crawl_date, full_data->'_order' AS tc_order, full_data->'_usage' AS tc_usage
        FROM card_tierlist_rankings
        WHERE crawl_date <= %s
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """, (result['crawl_date'] - timedelta(days=7),))
    prev = cur.fetchone()
    rank_change, prev_date = {}, ''
    if prev and not bucket:
        p_usage = prev['tc_usage'] or {}
        p_order = [tc for tc in (prev['tc_order'] or []) if tc not in EXCLUDE_TEAMCOLORS]
        if p_usage:
            p_order = [tc for tc in p_order if p_usage.get(tc, 0) >= MIN_USERS]
        p_rank = {tc: i for i, tc in enumerate(p_order, 1)}
        for i, tc in enumerate(order, 1):
            rank_change[tc] = (p_rank[tc] - i) if tc in p_rank else 'new'
        prev_date = str(prev['crawl_date'])

    cur.execute("""
        SELECT name, min_count, stat1_name, stat1_value, stat2_name, stat2_value,
               stat3_name, stat3_value, stat4_name, stat4_value
        FROM teamcolor_effects
        WHERE type = '소속' AND name = ANY(%s)
    """, (teamcolor_names,))

    effects = {}
    for row in cur.fetchall():
        stats = []
        for i in range(1, 5):
            stat_name = row[f'stat{i}_name']
            stat_value = row[f'stat{i}_value']
            if stat_name and stat_value is not None:
                stats.append({'name': stat_name, 'value': stat_value})
        effects[row['name']] = {
            'min_count': row['min_count'],
            'stats': stats
        }

    hover_map = {}
    price_map = {}
    if include_hover:
        # 화면에 나온 모든 카드의 spid + (spid, 강화단계) 조합 수집
        spid_set = set()
        pair_set = set()
        for tc in teamcolor_names:
            positions = full_data.get(tc, {})
            for pos_cards in positions.values():
                for card in pos_cards:
                    spid = int(card['spid'])
                    buildup = card['buildup']
                    spid_set.add(spid)
                    pair_set.add((spid, buildup))

        if spid_set:
            spid_list = list(spid_set)

            cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new'")
            new_trait_names = set(row['trait_name'] for row in cur.fetchall())

            cur.execute("""
                SELECT spid, full_data->'game_info' as game_info
                FROM player_cards
                WHERE spid = ANY(%s)
            """, (spid_list,))

            for row in cur.fetchall():
                game_info = row['game_info'] or {}
                traits = game_info.get('traits', [])
                new_trait = next((t for t in traits if t in new_trait_names), None)
                hover_map[row['spid']] = {
                    'salary': game_info.get('salary', ''),
                    'new_trait': new_trait
                }

            # (spid, 강화단계) 조합별로 필요한 최신 가격 값 하나만 DB에서 콕 집어서 조회
            pair_list = list(pair_set)
            price_rows = execute_values(cur, """
                SELECT v.spid, v.buildup,
                       cph.full_data #> ARRAY[v.buildup::text, 'values'] -> -1 AS latest_price
                FROM (VALUES %s) AS v(spid, buildup)
                JOIN card_price_history cph ON cph.spid = v.spid
            """, pair_list, template="(%s, %s)", fetch=True)

            for row in price_rows:
                if row['latest_price'] is not None:
                    price_map[f"{row['spid']}_{row['buildup']}"] = row['latest_price']

            # 위에서 못 찾은 조합만 card_prices(스냅샷)로 대체
            missing_pairs = [p for p in pair_list if f"{p[0]}_{p[1]}" not in price_map]
            if missing_pairs:
                missing_spids = list(set(p[0] for p in missing_pairs))
                cur.execute("""
                    SELECT spid, bp1, bp2, bp3, bp4, bp5, bp6, bp7, bp8, bp9, bp10, bp11, bp12, bp13
                    FROM card_prices
                    WHERE spid = ANY(%s)
                """, (missing_spids,))
                price_fallback_map = {row['spid']: row for row in cur.fetchall()}

                for spid, buildup in missing_pairs:
                    fb = price_fallback_map.get(spid)
                    if fb:
                        price = fb.get(f'bp{buildup}')
                        if price is not None:
                            price_map[f"{spid}_{buildup}"] = price

    cur.close()
    conn.close()

    response = {'success': True, 'data': full_data, 'effects': effects,
                'crawl_date': str(result['crawl_date']),
                'prev_date': prev_date, 'rank_change': rank_change,
                'bucket': bucket, 'bucket_label': bucket_label}
    if include_hover:
        response['hover_map'] = hover_map
        response['price_map'] = price_map
    return jsonify(response)

@app.route('/api/get_price_movers')
def get_price_movers():
    """시세 티어리스트: 기간별 급등/급락 탑30 (price_movers.py가 계산한 결과)"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new'")
    new_trait_names = set(row['trait_name'] for row in cur.fetchall())

    cur.execute("""
        SELECT pm.period, pm.direction, pm.rank, pm.spid, pm.grade,
               pm.prev_price, pm.cur_price, pm.change_rate, pm.updated_at,
               pc.player_name, pc.full_data->'game_info' AS game_info
        FROM price_movers pm
        LEFT JOIN player_cards pc ON pc.spid = pm.spid
        ORDER BY pm.period, pm.direction, pm.rank
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return jsonify({'success': False, 'message': '데이터가 없습니다'}), 404

    result = {}
    for row in rows:
        game_info = row['game_info'] or {}
        traits = game_info.get('traits', [])
        period_data = result.setdefault(str(row['period']), {'up': [], 'down': []})
        period_data[row['direction']].append({
            'rank': row['rank'],
            'spid': row['spid'],
            'grade': row['grade'],
            'prev_price': row['prev_price'],
            'cur_price': row['cur_price'],
            'change_rate': row['change_rate'],
            'name': row['player_name'] or '',
            'salary': game_info.get('salary', ''),
            'new_trait': next((t for t in traits if t in new_trait_names), None)
        })

    return jsonify({
        'success': True,
        'data': result,
        'updated_at': f"{rows[0]['updated_at'].month}월 {rows[0]['updated_at'].day}일"
    })
    
@app.route('/api/get_new_trait_stats')
def get_new_trait_stats():
    """신규 특성 티어리스트: 포지션별 카드 고유(ranker) / 8강 선택(nexon) TOP 5"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT source, position, rank, trait_name, count, ratio, data_date, diff, prev_date
        FROM new_trait_stats
        ORDER BY source, position, rank
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return jsonify({'success': False, 'message': '데이터가 없습니다'}), 404

    def to_korean_date(text):
        try:
            d = datetime.strptime(text[:10], '%Y-%m-%d')
            return f"{d.month}월 {d.day}일"
        except Exception:
            return ''

    result = {'ranker': {}, 'nexon': {}}
    dates, prev_dates = {}, {}
    for row in rows:
        result[row['source']].setdefault(row['position'], []).append({
            'rank': row['rank'],
            'name': row['trait_name'],
            'count': row['count'],
            'ratio': row['ratio'],
            'diff': row['diff'],
            'is_new': row['diff'] is None and bool(row['prev_date'])
        })
        dates[row['source']] = to_korean_date(row['data_date'] or '')
        if row['prev_date']:
            prev_dates[row['source']] = to_korean_date(row['prev_date'])

    return jsonify({
        'success': True,
        'data': result,
        'ranker_date': dates.get('ranker', ''),
        'nexon_date': dates.get('nexon', ''),
        'ranker_prev_date': prev_dates.get('ranker', ''),
        'nexon_prev_date': prev_dates.get('nexon', '')
    })    

@app.route('/api/squad_tierlist_teamcolors')
def squad_tierlist_teamcolors():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT full_data->'_order' AS tc_order, full_data->'_logos' AS tc_logos,
               full_data->'_usage' AS tc_usage
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """)
    result = cur.fetchone()
    cur.execute("SELECT team_name, logo_url FROM team_logos")
    table_logos = {row['team_name']: row['logo_url'] for row in cur.fetchall()}
    crawled_logos = (result['tc_logos'] if result else None) or {}
    logos = {**crawled_logos, **table_logos}
    cur.close()
    conn.close()
    if not result:
        return jsonify({'success': False}), 404
    order = result['tc_order'] or []
    order = [tc for tc in order if tc not in TIERLIST_EXCLUDE_TEAMCOLORS]
    usage = result['tc_usage'] or {}
    if usage:
        order = [tc for tc in order if usage.get(tc, 0) >= TIERLIST_MIN_USERS]
    return jsonify({'success': True, 'order': order, 'logos': logos})

@app.route('/api/squad_tierlist_cards')
def squad_tierlist_cards():
    """스쿼드 메이커용 특정 팀컬러 카드 데이터 반환"""
    teamcolor = request.args.get('teamcolor', '').strip()
    if not teamcolor:
        return jsonify({'success': False}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT full_data->%s AS tc_data
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """, (teamcolor,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result or not result['tc_data']:
        return jsonify({'success': False}), 404
    return jsonify({'success': True, 'data': result['tc_data']})


@app.route('/api/squad_cards_batch', methods=['POST'])
def squad_cards_batch():
    spids = request.json.get('spids', [])
    if not spids:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT spid, player_name, season_name, overall, position,
               COALESCE(full_data->'image_info'->>'mini_faceon',
                        full_data->'image_info'->>'mini_faceon_high') as image,
               full_data->'image_info'->>'mini_faceon_high' as image_high,
               full_data->'image_info'->>'season_img' as season_img,
               full_data->'game_info'->>'salary' as salary,
               full_data->'stats_info'->'position_overall' as position_overall,
               full_data->'stats_info'->'main_overall'->>'card_position' as card_position,
               full_data->'game_info'->'traits' as traits
        FROM player_cards
        WHERE spid = ANY(%s)
    """, (spids,))
    cards = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(cards)

@app.route('/api/ranker_squad_list')
def ranker_squad_list():
    """랭커 스쿼드 목록 반환 (팀컬러 + 구단가치 범위 필터)"""
    teamcolor = request.args.get('teamcolor', '').strip()
    min_val = request.args.get('min', 0, type=int)
    max_val = request.args.get('max', 0, type=int)
    if not teamcolor:
        return jsonify({'success': False}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT squad_full_data->%s AS tc_data
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """, (teamcolor,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result or not result['tc_data']:
        return jsonify({'success': True, 'data': []})

    rankers = result['tc_data']
    if max_val > 0:
        rankers = [r for r in rankers if min_val <= r.get('squad_value', 0) <= max_val]

    # 순위 오름차순 정렬, 최대 50명
    # nickname 중복 제거 (rank 낮은 것 우선)
    seen = {}
    for r in sorted(rankers, key=lambda x: x['rank']):
        if r['nickname'] not in seen:
            seen[r['nickname']] = r
    rankers = list(seen.values())[:50]
    return jsonify({'success': True, 'data': rankers})


@app.route('/api/ranker_squad_detail')
def ranker_squad_detail():
    """특정 랭커 스쿼드 상세 정보 반환"""
    teamcolor = request.args.get('teamcolor', '').strip()
    rank = request.args.get('rank', 0, type=int)
    if not teamcolor or not rank:
        return jsonify({'success': False}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT squad_full_data->%s AS tc_data
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """, (teamcolor,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result or not result['tc_data']:
        return jsonify({'success': False}), 404

    ranker = next((r for r in result['tc_data'] if r['rank'] == rank), None)
    if not ranker:
        return jsonify({'success': False}), 404

    return jsonify({'success': True, 'data': ranker})

@app.route('/api/ranker_squad_list_all')
def ranker_squad_list_all():
    """전체 팀컬러 통합 랭커 목록 반환 (구단가치 범위 + 팀컬러 필터, 서버 전체 순위 기준 정렬)"""
    min_val = request.args.get('min', 0, type=int)
    max_val = request.args.get('max', 0, type=int)
    tc_filter_raw = request.args.get('teamcolors', '', type=str)
    tc_filter = set(t for t in tc_filter_raw.split(',') if t)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT squad_full_data
        FROM card_tierlist_rankings
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
    """)
    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result or not result['squad_full_data']:
        return jsonify({'success': True, 'data': []})

    all_data = result['squad_full_data']
    combined = []
    
    for tc, rankers in all_data.items():
        if tc == '_order' or not isinstance(rankers, list):
            continue
        if tc_filter and tc not in tc_filter:
            continue
        filtered = rankers
        if max_val > 0:
            filtered = [r for r in filtered if min_val <= r.get('squad_value', 0) <= max_val]

        # 팀컬러 내 nickname 중복 제거 (rank 낮은 것 우선)
        seen = {}
        for r in sorted(filtered, key=lambda x: x['rank']):
            if r['nickname'] not in seen:
                seen[r['nickname']] = r
        for r in seen.values():
            r['teamcolor'] = tc
            combined.append(r)

    # 서버 전체 순위 기준 오름차순 정렬, 최대 100명
    combined = sorted(combined, key=lambda x: x['rank'])[:100]
    return jsonify({'success': True, 'data': combined})

@app.route('/api/get_all_formation_data')
def get_all_formation_data():
    """모든 날짜의 포메이션 데이터 반환 (최근 6개)"""
    ranking = request.args.get('ranking', '10000')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 최근 6개 날짜 데이터 가져오기 (5배수 간격)
    cur.execute("""
        SELECT crawl_date, full_data 
        FROM formation_rankings 
        ORDER BY crawl_date DESC 
        LIMIT 6
    """)
    
    results = []
    for row in cur.fetchall():
        date = row['crawl_date'].strftime('%m-%d')  # MM-DD 형식
        full_data = row['full_data']
        
        # 해당 ranking_range 찾기
        for dataset in full_data:
            if dataset['ranking_range'] == f'1-{ranking}':
                results.append({
                    'date': date,
                    'formations': dataset['formations'][:10]  # 상위 10개
                })
                break
    
    # 날짜순 정렬 (오래된 것부터)
    results.reverse()
    
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'data': results})


@app.route('/squad_maker')
def squad_maker():
    """스쿼드 메이커 페이지"""
    share_param = request.args.get('share', '')
    is_logged_in = 'user_id' in session
    if share_param:
        og_title = "FCOnQ - 스쿼드 공유"
        og_description = "공유된 FC온라인 스쿼드를 확인해보세요!"
    else:
        og_title = "FCOnQ - FC온라인 전문 선수 DB 및 커뮤니티"
        og_description = "8만개 이상의 선수 카드 정보와 시세를 확인하고, FC온라인 유저들과 소통하세요!"

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT trait_name FROM player_traits WHERE trait_type = 'new' ORDER BY trait_name")
        new_traits = [row['trait_name'] for row in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    return render_template('squad_maker.html', og_title=og_title, og_description=og_description,
                           is_logged_in=is_logged_in, new_traits=new_traits)


@app.route('/api/user_squad/save', methods=['POST'])
def user_squad_save():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.json
    name = data.get('name', '').strip()
    squad_data = data.get('squad_data')
    if not name or not squad_data:
        return jsonify({'error': 'invalid data'}), 400
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM user_squads WHERE user_id = %s", (session['user_id'],))
            count = cur.fetchone()['count']
            if count >= 30:
                return jsonify({'error': '최대 30개까지 저장 가능합니다'}), 400
            cur.execute("""
                INSERT INTO user_squads (user_id, name, squad_data, created_at)
                VALUES (%s, %s, %s, NOW())
                RETURNING id
            """, (session['user_id'], name, json.dumps(squad_data)))
            new_id = cur.fetchone()['id']
        conn.commit()
    return jsonify({'success': True, 'id': new_id})

@app.route('/api/user_squad/load', methods=['GET'])
def user_squad_load():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, squad_data, created_at
                FROM user_squads WHERE user_id = %s
                ORDER BY created_at DESC
            """, (session['user_id'],))
            squads = cur.fetchall()
    return jsonify([{
        'id': s['id'],
        'name': s['name'],
        'squad_data': s['squad_data'],
        'created_at': s['created_at'].strftime('%Y-%m-%d %H:%M')
    } for s in squads])

@app.route('/api/user_squad/delete', methods=['POST'])
def user_squad_delete():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    squad_id = request.json.get('id')
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM user_squads WHERE id = %s AND user_id = %s
            """, (squad_id, session['user_id']))
        conn.commit()
    return jsonify({'success': True})


@app.route('/api/squad_search')
@app.route('/api/squad_search')
def squad_search():
    """스쿼드 메이커 선수 검색 API"""
    term = request.args.get('q', '').strip()
    pos = request.args.get('pos', '').strip()
    
    if not term:
        return jsonify([])
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        query = """
            SELECT spid, player_name, season_name, overall, position,
                   COALESCE(full_data->'image_info'->>'mini_faceon', full_data->'image_info'->>'mini_faceon_high') as image,
                   full_data->'image_info'->>'season_img' as season_img,
                   full_data->'game_info'->>'salary' as salary,
                   full_data->'image_info'->>'mini_faceon_high' as image_high,
                   full_data->'stats_info'->'position_overall' as position_overall,
                   full_data->'game_info'->'traits' as traits
            FROM player_cards
            WHERE player_name ILIKE %s
            ORDER BY overall DESC
            LIMIT 100
        """
        cur.execute(query, (f"%{term}%",))
        cards = [dict(row) for row in cur.fetchall()]
        
        cur.close()
    finally:
        conn.close()
    
    return jsonify(cards)


@app.route('/api/squad_search_by_pid', methods=['GET', 'POST'])
def squad_search_by_pid():
    """동일 선수(pid 기준) 카드 목록 반환"""
    if request.method == 'POST':
        data = request.get_json()
        spids = data.get('spids', [])
        if not spids:
            return jsonify([])
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT spid, player_name, season_name, overall, position,
                   COALESCE(full_data->'image_info'->>'mini_faceon', full_data->'image_info'->>'mini_faceon_high') as image,
                   full_data->'image_info'->>'season_img' as season_img,
                   full_data->'game_info'->>'salary' as salary,
                   full_data->'image_info'->>'mini_faceon_high' as image_high,
                   full_data->'stats_info'->'position_overall' as position_overall,
                   full_data->'game_info'->'traits' as traits
            FROM player_cards
            WHERE spid = ANY(%s)
        """, (spids,))
        cards = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(cards)

    # GET: 기존 단일 spid 조회
    spid = request.args.get('spid', '').strip()
    if not spid or len(spid) < 9:
        return jsonify([])
    pid = spid[-6:]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT spid, player_name, season_name, overall, position,
               COALESCE(full_data->'image_info'->>'mini_faceon', full_data->'image_info'->>'mini_faceon_high') as image,
               full_data->'image_info'->>'season_img' as season_img,
               full_data->'game_info'->>'salary' as salary,
               full_data->'image_info'->>'mini_faceon_high' as image_high,
               full_data->'stats_info'->'position_overall' as position_overall,
               full_data->'game_info'->'traits' as traits
        FROM player_cards
        WHERE RIGHT(spid::text, 6) = %s
        ORDER BY overall DESC
    """, (pid,))
    cards = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(cards)

@app.route('/api/squad_teamcolor', methods=['POST'])
def squad_teamcolor():
    """스쿼드 소속 팀컬러 효과 조회"""
    data = request.get_json()
    spids = data.get('spids', [])
    if not spids:
        return jsonify([])

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT spid,
               full_data->'basic_info'->>'nation' as nation,
               full_data->'basic_info'->'club_history' as club_history,
               season_name
        FROM player_cards
        WHERE spid = ANY(%s)
    """, (spids,))
    cards = [dict(row) for row in cur.fetchall()]

    from collections import defaultdict
    import json as _json
    groups = defaultdict(set)
    season_groups = defaultdict(set)

    SPECIAL_SEASONS = {'TOTY', 'TOTS', 'ICONTM'}
    SEASON_THRESHOLDS = [3, 6, 8]
    SEASON_OVR_MAP = {1: 1, 2: 2, 3: 3}

    for card in cards:
        if card['nation']:
            nation = card['nation'].split(',')[0].strip()
            groups[nation].add(card['spid'])
        if card['club_history']:
            clubs = card['club_history'] if isinstance(card['club_history'], list) else _json.loads(card['club_history'])
            for club_item in clubs:
                club_name = club_item.get('club') if isinstance(club_item, dict) else club_item
                if club_name:
                    groups[club_name].add(card['spid'])
        if card['season_name']:
            sn = card['season_name']
            if sn.endswith('TOTY') or sn.endswith('TOTN'):
                season_key = 'TOTY'
            elif sn.endswith('TOTS'):
                season_key = 'TOTS'
            elif sn == 'ICONTM':
                season_key = 'ICONTM'
            else:
                season_key = sn
            season_groups[season_key].add(card['spid'])

    result = []

    # 국가/클럽 팀컬러
    for tc_name, tc_spids in groups.items():
        tc_spids = list(tc_spids)
        cur.execute("SELECT * FROM teamcolor_effects WHERE name = %s", (tc_name,))
        effect = cur.fetchone()
        if not effect:
            continue
        effect = dict(effect)
        cnt = len(tc_spids)
        if cnt < 3:
            continue

        thresholds = [3, 6, 8, 11]
        stage = 0
        for i, t in enumerate(thresholds[:effect['max_stage']]):
            if cnt >= t:
                stage = i + 1
        if stage == 0:
            continue

        ovr_map = {1: 1, 2: 3, 3: 3, 4: effect['ovr_bonus']}
        result.append({
            'name': effect['name'],
            'type': effect['type'],
            'image_url': effect['image_url'],
            'stage': stage,
            'max_stage': effect['max_stage'],
            'cnt': cnt,
            'spids': tc_spids,
            'ovr_bonus': ovr_map.get(stage, 0),
            'stat1_name': effect['stat1_name'] if stage >= effect['max_stage'] - 1 else None,
            'stat1_value': (2 if stage == effect['max_stage'] - 1 else effect['stat1_value']) if stage >= effect['max_stage'] - 1 else None,
            'stat2_name': effect['stat2_name'] if stage >= effect['max_stage'] - 1 else None,
            'stat2_value': (1 if stage == effect['max_stage'] - 1 else effect['stat2_value']) if stage >= effect['max_stage'] - 1 else None,
        })

    # 시즌 팀컬러
    for season_key, s_spids in season_groups.items():
        s_spids = list(s_spids)
        cnt = len(s_spids)
        if cnt < 3:
            continue

        stage = 0
        for i, t in enumerate(SEASON_THRESHOLDS):
            if cnt >= t:
                stage = i + 1

        stat1_name = stat1_value = stat2_name = stat2_value = None
        if season_key in SPECIAL_SEASONS:
            cur.execute("SELECT * FROM teamcolor_effects WHERE name = %s", (season_key,))
            effect = cur.fetchone()
            if effect:
                effect = dict(effect)
                if stage == 3:
                    stat1_name = effect['stat1_name']
                    stat1_value = effect['stat1_value']
                    stat2_name = effect['stat2_name']
                    stat2_value = effect['stat2_value']

        result.append({
            'name': season_key,
            'type': 'season',
            'image_url': None,
            'stage': stage,
            'max_stage': 3,
            'cnt': cnt,
            'spids': s_spids,
            'ovr_bonus': SEASON_OVR_MAP.get(stage, 0),
            'stat1_name': stat1_name,
            'stat1_value': stat1_value,
            'stat2_name': stat2_name,
            'stat2_value': stat2_value,
        })

    cur.close()
    conn.close()
    
    result.sort(key=lambda x: (x['stage'], x['cnt']), reverse=True)
    assigned = set()
    for tc in result:
        unique_spids = [s for s in tc['spids'] if s not in assigned]
        assigned.update(unique_spids)
        tc['display_spids'] = unique_spids  # 미페 표시용 (교집합 제외)
        # cnt와 spids는 원래 전체 인원 유지
    result = [tc for tc in result if tc['stage'] > 0]
    
    return jsonify(result)

@app.route('/api/squad_trait_teamcolor', methods=['POST'])
def squad_trait_teamcolor():
    """스쿼드 특성 팀컬러 효과 조회"""
    data = request.get_json()
    spids = data.get('spids', [])
    if not spids:
        return jsonify([])

    conn = get_db_connection()
    cur = conn.cursor()

    # spid → pid 추출
    pids = [str(spid)[-6:] for spid in spids]
    pid_to_spid = {str(spid)[-6:]: spid for spid in spids}

    # 각 특성 팀컬러별로 매칭되는 pid 파악
    cur.execute("""
        SELECT sc.name, scp.player_id
        FROM special_teamcolor_players scp
        JOIN special_teamcolors sc ON scp.teamcolor_id = sc.id
        WHERE scp.player_id = ANY(%s)
    """, (pids,))
    rows = cur.fetchall()

    from collections import defaultdict
    tc_pids = defaultdict(set)
    for row in rows:
        tc_pids[row['name']].add(row['player_id'])

    result = []
    for tc_name, matched_pids in tc_pids.items():
        cur.execute("SELECT * FROM teamcolor_effects WHERE name = %s AND type = '특성'", (tc_name,))
        effect = cur.fetchone()
        if not effect:
            continue
        effect = dict(effect)
        cnt = len(matched_pids)
        if cnt < effect['min_count']:
            continue

        matched_spids = [pid_to_spid[pid] for pid in matched_pids if pid in pid_to_spid]
        result.append({
            'name': tc_name,
            'type': 'trait',
            'image_url': effect['image_url'],
            'cnt': cnt,
            'min_count': effect['min_count'],
            'spids': matched_spids,
            'display_spids': matched_spids,
            'stat1_name': effect['stat1_name'],
            'stat1_value': effect['stat1_value'],
            'stat2_name': effect['stat2_name'],
            'stat2_value': effect['stat2_value'],
            'stat3_name': effect.get('stat3_name'),
            'stat3_value': effect.get('stat3_value'),
            'stat4_name': effect.get('stat4_name'),
            'stat4_value': effect.get('stat4_value'),
        })

    cur.close()
    conn.close()

    result.sort(key=lambda x: x['cnt'], reverse=True)
    return jsonify(result)

@app.route('/api/card_price/<int:spid>')
def card_price(spid):
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT full_data
            FROM card_price_history
            WHERE spid = %s
        """, (spid,))
        row = cur.fetchone()

        if row and row['full_data']:
            result = {}
            for boost_str, data in row['full_data'].items():
                values = data.get('values', []) if isinstance(data, dict) else data
                if values:
                    result[f'bp{boost_str}'] = values[-1]
            if result:
                cur.close()
                return jsonify(result)

        cur.execute("""
            SELECT bp1, bp2, bp3, bp4, bp5, bp6, bp7,
                   bp8, bp9, bp10, bp11, bp12, bp13
            FROM card_prices
            WHERE spid = %s
        """, (spid,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return jsonify({})
    return jsonify(dict(row))

# ── 구단주명으로 스쿼드 조회 (넥슨 오픈 API) ─────────────────
NEXON_API_KEY = os.getenv('NEXON_API_KEY')
NEXON_API_BASE = 'https://open.api.nexon.com/fconline/v1'
OFFICIAL_MATCH_TYPE = 50  # 공식경기(1vs1)

# 넥슨 포지션 번호 → 스쿼드 메이커 포지션명 (28번은 후보라 제외)
NEXON_SPPOSITION = {
    0: 'GK', 1: 'SW', 2: 'RWB', 3: 'RB', 4: 'RCB', 5: 'CB', 6: 'LCB', 7: 'LB', 8: 'LWB',
    9: 'RDM', 10: 'CDM', 11: 'LDM', 12: 'RM', 13: 'RCM', 14: 'CM', 15: 'LCM', 16: 'LM',
    17: 'RAM', 18: 'CAM', 19: 'LAM', 20: 'RF', 21: 'CF', 22: 'LF', 23: 'RW', 24: 'RS',
    25: 'ST', 26: 'LS', 27: 'LW'
}
_owner_squad_cache = {}  # 같은 구단주명 반복 검색 시 3분간 재사용


def nexon_get(path, params):
    """넥슨 오픈 API 호출"""
    url = f"{NEXON_API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'x-nxopen-api-key': NEXON_API_KEY})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode('utf-8'))


@app.route('/api/owner_squad')
def owner_squad():
    """구단주명 → 최근 공식경기 출전 라인업"""
    nickname = request.args.get('nickname', '').strip()
    if not nickname:
        return jsonify({'success': False, 'message': '구단주명을 입력해주세요.'}), 400
    if not NEXON_API_KEY:
        return jsonify({'success': False, 'message': '서버 설정 오류입니다.'}), 500

    now = datetime.now()
    cached = _owner_squad_cache.get(nickname)
    if cached and (now - cached['time']).total_seconds() < 180:
        return jsonify(cached['data'])

    # 1) 구단주명 → ouid
    try:
        ouid = nexon_get('/id', {'nickname': nickname}).get('ouid')
    except urllib.error.HTTPError:
        return jsonify({'success': False, 'message': '존재하지 않는 구단주명입니다.'}), 404
    except Exception:
        return jsonify({'success': False, 'message': '넥슨 서버 응답이 없습니다. 잠시 후 다시 시도해주세요.'}), 502
    if not ouid:
        return jsonify({'success': False, 'message': '존재하지 않는 구단주명입니다.'}), 404

    # 2) 최근 공식경기 목록
    try:
        match_ids = nexon_get('/user/match', {
            'ouid': ouid, 'matchtype': OFFICIAL_MATCH_TYPE, 'offset': 0, 'limit': 5
        })
    except Exception:
        return jsonify({'success': False, 'message': '넥슨 서버 응답이 없습니다. 잠시 후 다시 시도해주세요.'}), 502
    if not match_ids:
        return jsonify({'success': False, 'message': '최근 공식경기 기록이 없습니다.'}), 404

    # 3) 최근 경기부터 확인해서 11명이 다 있는 라인업 찾기 (몰수·기권 경기 대비)
    for match_id in match_ids:
        try:
            detail = nexon_get('/match-detail', {'matchid': match_id})
        except Exception:
            continue
        me = next((m for m in detail.get('matchInfo', []) if m.get('ouid') == ouid), None)
        if not me:
            continue
        squad = []
        for p in me.get('player', []):
            pos = NEXON_SPPOSITION.get(p.get('spPosition'))
            if pos:
                squad.append({'position': pos, 'spid': p.get('spId'), 'buildup': p.get('spGrade') or 1})
        if len(squad) >= 11:
            data = {
                'success': True,
                'nickname': me.get('nickname', nickname),
                'match_date': detail.get('matchDate', ''),
                'squad': squad
            }
            if len(_owner_squad_cache) > 500:
                _owner_squad_cache.clear()
            _owner_squad_cache[nickname] = {'data': data, 'time': now}
            return jsonify(data)

    return jsonify({'success': False, 'message': '최근 공식경기에서 스쿼드 정보를 찾지 못했습니다.'}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)