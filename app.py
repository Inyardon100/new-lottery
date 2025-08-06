import streamlit as st
import sqlite3
import random
import time
import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- 시간대 설정 (한국시간) ---
KST = datetime.timezone(datetime.timedelta(hours=9))

def now_kst():
    return datetime.datetime.now(KST)

# --- 1. 데이터베이스 초기화 ---
def setup_database():
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.executescript('''
    CREATE TABLE IF NOT EXISTS lotteries (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        draw_time TIMESTAMP,
        num_winners INTEGER,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY,
        lottery_id INTEGER,
        name TEXT NOT NULL,
        FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS winners (
        id INTEGER PRIMARY KEY,
        lottery_id INTEGER,
        winner_name TEXT,
        draw_round INTEGER,
        FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS lottery_logs (
        id INTEGER PRIMARY KEY,
        lottery_id INTEGER,
        log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        log_message TEXT,
        FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    ''')
    conn.commit()
    return conn

# --- 헬퍼 함수 ---
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message) VALUES (?, ?)", (lottery_id, message))
    conn.commit()

def run_draw(conn, lottery_id, num_to_draw, candidates):
    actual = min(num_to_draw, len(candidates))
    if actual <= 0:
        return []
    winners = random.sample(candidates, k=actual)
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    prev = c.fetchone()[0] or 0
    current_round = prev + 1
    for w in winners:
        c.execute("INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)", (lottery_id, w, current_round))
    c.execute("UPDATE lotteries SET status='completed' WHERE id=?", (lottery_id,))
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 진행. 당첨자: {', '.join(winners)}")
    return winners

def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    now = now_kst()
    c.execute("SELECT id, num_winners FROM lotteries WHERE status='scheduled' AND draw_time<=?", (now,))
    for lid, num in c.fetchall():
        names = [r[0] for r in c.execute("SELECT name FROM participants WHERE lottery_id=?", (lid,))]
        if names:
            winners = run_draw(conn, lid, num, names)
            if winners:
                st.session_state[f'celebrated_{lid}'] = True

# --- Streamlit UI ---
def main():
    st.set_page_config(page_title="new lottery", page_icon="📜", layout="wide")
    st_autorefresh(interval=1000, limit=None, key="refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    # 세션 초기화
    st.session_state.setdefault('admin_auth', False)
    st.session_state.setdefault('delete_confirm_id', None)

    st.title("📜 NEW LOTTERY")
    col1, col2 = st.columns([2, 1])

    # --- 진행 중인 추첨 선택 ---
    with col1:
        st.header("🎉 진행 중인 추첨")
        st.markdown("---")
        df = pd.read_sql("SELECT id, title, draw_time, status, num_winners FROM lotteries ORDER BY id DESC", conn)
        ongoing = df[df['status'] == 'scheduled']
        if ongoing.empty:
            st.info("진행 중인 추첨이 없습니다.")
        else:
            choice = st.selectbox("추첨 선택", ongoing['title'], key="ongoing_choice")
            sel = ongoing[ongoing['title'] == choice].iloc[0]
            lid = int(sel['id'])
            title = sel['title']
            raw_time = sel['draw_time']
            if isinstance(raw_time, str):
                draw_time = datetime.datetime.fromisoformat(raw_time)
            else:
                draw_time = raw_time
            if draw_time.tzinfo is None:
                draw_time = draw_time.replace(tzinfo=KST)

            st.subheader(f"✨ {title}")
            diff = draw_time - now_kst()
            if diff.total_seconds() > 0:
                st.info(f"추첨 예정: {draw_time.strftime('%Y-%m-%d %H:%M:%S')} (남은 시간: {str(diff).split('.')[0]})")
            else:
                st.warning("예정 시간이 지났습니다. 곧 자동 진행됩니다...")

            tabs = st.tabs(["참가자 명단", "추첨 로그"])
            names = [r[0] for r in conn.execute("SELECT name FROM participants WHERE lottery_id=?", (lid,))]
            with tabs[0]:
                if names:
                    st.write("\n".join(names))
                else:
                    st.info("참가자가 없습니다.")

            logs = pd.read_sql(
                "SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp) AS 시간, log_message AS 내용 "
                "FROM lottery_logs WHERE lottery_id=? ORDER BY id", conn, params=(lid,)
            )
            with tabs[1]:
                st.dataframe(logs)

    # --- 관리자 메뉴 ---
    with col2:
        st.header("👑 관리자")
        if not st.session_state['admin_auth']:
            pw = st.text_input("관리자 코드", type="password")
            if st.button("인증"):
                if pw == st.secrets.get('admin', {}).get('password'):
                    st.session_state['admin_auth'] = True
                    st.experimental_rerun()
                else:
                    st.error("관리자 코드가 일치하지 않습니다.")
        else:
            st.success("관리자 모드")
            action = st.radio("작업 선택", ["새 추첨 생성", "기존 추첨 관리"], key="admin_action_radio")

            if action == "새 추첨 생성":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", min_value=1, value=1, key="new_num_winners")
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], key="new_draw_type")

                if draw_type == "예약 추첨":
                    date = st.date_input("추첨 날짜 (YYYY-MM-DD)", value=now_kst().date(), key="new_draw_date")
                    default_tm = st.session_state.get('new_draw_time', now_kst().time())
                    tm = st.time_input("추첨 시간 (HH:MM)", value=default_tm, key="new_draw_time", step=60)
                    draw_time = datetime.datetime.combine(date, tm, tzinfo=KST)
                else:
                    draw_time = now_kst()

                st.markdown("참가자 명단을 입력하세요. 한 줄에 한 명씩 입력합니다.")
                participants_txt = st.text_area("참가자 (예: 홍길동)\n홍길순", key="new_participants", height=150)
                if st.button("추첨 생성", key="create_button"):
                    names = [n.strip() for n in participants_txt.split('\n') if n.strip()]
                    if not title or not names:
                        st.warning("제목과 최소 한 명 이상의 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time <= now_kst():
                        st.error("예약 추첨 시간은 현재 시간 이후여야 합니다.")
                    else:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')",
                            (title, draw_time, num_winners)
                        )
                        lid = c.lastrowid
                        for n in names:
                            c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lid, n))
                        conn.commit()
                        add_log(conn, lid, f"추첨 생성 (방식: {draw_type}, 참가자 수: {len(names)})")
                        st.success("추첨이 생성되었습니다.")
                        time.sleep(1)
                        st.experimental_rerun()

            else:
                st.subheader("기존 추첨 관리")
                df_all = pd.read_sql("SELECT id, title, status FROM lotteries ORDER BY id DESC", conn)
                if df_all.empty:
                    st.info("관리할 추첨이 없습니다.")
                else:
                    choice = st.selectbox("추첨 선택", df_all['title'], key="manage_choice")
                    sel = df_all[df_all['title'] == choice].iloc[0]
                    lid = int(sel['id'])

                    # 재추첨
                    if sel['status'] == 'completed':
                        st.write("**재추첨**")
                        all_participants = pd.read_sql(
                            "SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lid,)
                        )['name'].tolist()
                        prev_winners = pd.read_sql(
                            "SELECT winner_name FROM winners WHERE lottery_id = ?", conn, params=(lid,)
                        )['winner_name'].tolist()
                        candidates = [p for p in all_participants if p not in prev_winners]
                        if candidates:
                            chosen = st.multiselect("재추첨 대상자", candidates, default=candidates, key="redraw_candidates")
                            num_redraw = st.number_input("추첨 인원", min_value=1, max_value=len(chosen), value=1, key="redraw_num")
                            if st.button("재추첨 실행", key="redraw_button"):
                                run_draw(conn, lid, num_redraw, chosen)
                                st.success("재추첨이 완료되었습니다.")
                                time.sleep(1)
                                st.experimental_rerun()
                        else:
                            st.warning("재추첨 대상자가 없습니다.")

                    st.markdown("---")
                    # 삭제
                    if st.button("삭제 확인", key="delete_button"):
                        st.session_state['delete_confirm_id'] = lid
                    if st.session_state['delete_confirm_id'] == lid:
                        st.warning("정말 이 추첨을 삭제하시겠습니까? 이 작업은 복구가 불가능합니다.")
                        if st.button("예, 삭제합니다", key="confirm_delete"):
                            c = conn.cursor()
                            c.execute("DELETE FROM lottery_logs WHERE lottery_id=?", (lid,))
                            c.execute("DELETE FROM winners WHERE lottery_id=?", (lid,))
                            c.execute("DELETE FROM participants WHERE lottery_id=?", (lid,))
                            c.execute("DELETE FROM lotteries WHERE id=?", (lid,))
                            conn.commit()
                            st.success("추첨 및 관련 데이터가 삭제되었습니다.")
                            time.sleep(1)
                            st.experimental_rerun()

    conn.close()

if __name__ == '__main__':
    main()
