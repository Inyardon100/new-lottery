import streamlit as st
import sqlite3
import random
import time
import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- 시간대 설정 (한국시간) ---
KST = datetime.timezone(datetime.timedelta(hours=9))

# --- 1. 설정 및 데이터베이스 초기화 ---
def setup_database():
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.execute('''
        CREATE TABLE IF NOT EXISTS lotteries (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            draw_time TIMESTAMP,
            num_winners INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY,
            lottery_id INTEGER,
            name TEXT NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY,
            lottery_id INTEGER,
            winner_name TEXT,
            draw_round INTEGER,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS lottery_logs (
            id INTEGER PRIMARY KEY,
            lottery_id INTEGER,
            log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_message TEXT,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    return conn

# --- 2. 헬퍼 및 로직 함수 ---
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute(
        "INSERT INTO lottery_logs (lottery_id, log_message) VALUES (?, ?)",
        (lottery_id, message)
    )
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
        c.execute(
            "INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)",
            (lottery_id, w, current_round)
        )
    c.execute("UPDATE lotteries SET status = 'completed' WHERE id = ?", (lottery_id,))
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 진행. (당첨자: {', '.join(winners)})")
    return winners


def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    now = datetime.datetime.now(KST)
    c.execute(
        "SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?", (now,)
    )
    for lottery_id, num_winners in c.fetchall():
        c.execute("SELECT name FROM participants WHERE lottery_id = ?", (lottery_id,))
        participants = [r[0] for r in c.fetchall()]
        if participants:
            winners = run_draw(conn, lottery_id, num_winners, participants)
            if winners:
                st.session_state[f'celebrated_{lottery_id}'] = True


# --- 3. Streamlit UI 구성 ---
def main():
    st.set_page_config(page_title="new lottery", page_icon="📜", layout="wide")
    st_autorefresh(interval=5000, limit=None, key="main_refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    # 세션 상태 초기화
    if 'admin_auth' not in st.session_state:
        st.session_state['admin_auth'] = False
    if 'delete_confirm_id' not in st.session_state:
        st.session_state['delete_confirm_id'] = None

    st.title("📜 NEW LOTTERY")
    st.markdown("---")
    col1, col2 = st.columns([2, 1])

    with col1:
        st.header("🎉 추첨 현황판")
        st.markdown("이 페이지는 최신 상태를 반영합니다.")
        try:
            lotteries_df = pd.read_sql(
                "SELECT id, title, draw_time, status, num_winners FROM lotteries ORDER BY id DESC", conn
            )
        except:
            lotteries_df = pd.DataFrame()

        if lotteries_df.empty:
            st.info("아직 생성된 추첨이 없습니다. 관리자가 추첨을 만들어주세요.")
        else:
            for _, row in lotteries_df.iterrows():
                lid = int(row['id'])
                title = row['title']
                status = row['status']
                draw_time = pd.to_datetime(row['draw_time'])
                with st.container():
                    st.subheader(f"✨ {title}")
                    winners_df = pd.read_sql(
                        "SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round",
                        conn, params=(lid,)
                    )
                    if not winners_df.empty:
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S')})")
                        for rnd, grp in winners_df.groupby('draw_round'):
                            label = '1회차' if rnd == 1 else f"{rnd}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {label} 당첨자")
                            tags = " &nbsp; ".join([
                                f"<span style='background-color:#E8F5E9; color:#1E8E3E; border-radius:5px; padding:5px 10px; font-weight:bold;'>{n}</span>"
                                for n in grp['winner_name']
                            ])
                            st.markdown(f"<p style='text-align:center; font-size:20px;'>{tags}</p>", unsafe_allow_html=True)
                        if st.session_state.get(f'celebrated_{lid}', False):
                            st.balloons()
                            st.session_state[f'celebrated_{lid}'] = False
                    else:
                        diff = draw_time - datetime.datetime.now(KST)
                        if diff.total_seconds() > 0:
                            st.info(f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S')} (남은 시간: {str(diff).split('.')[0]})")
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 추첨이 자동으로 진행됩니다...")

                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        participants_df = pd.read_sql(
                            "SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lid,)
                        )
                        st.dataframe(participants_df.rename(columns={'name':'이름'}), use_container_width=True, height=150)
                    with tab2:
                        logs_df = pd.read_sql(
                            "SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp, 'localtime') AS 시간, log_message AS 내용"
                            " FROM lottery_logs WHERE lottery_id = ? ORDER BY id", conn, params=(lid,)
                        )
                        st.dataframe(logs_df, use_container_width=True, height=150)

    with col2:
        st.header("👑 추첨 관리자 메뉴")
        if not st.session_state.admin_auth:
            pw = st.text_input("관리자 코드를 입력하세요.", type="password", key="admin_pw_input")
            if st.button("인증", key="auth_button"):
                try:
                    if pw == st.secrets['admin']['password']:
                        st.session_state.admin_auth = True
                        st.experimental_rerun()
                    else:
                        st.error("코드가 올바르지 않습니다.")
                except KeyError:
                    st.error("Secrets 설정을 확인해주세요. 관리자 코드가 설정되지 않았습니다.")
        else:
            st.success("관리자로 인증되었습니다.")
            action = st.radio(
                "작업 선택", ["새 추첨 만들기", "기존 추첨 관리 (재추첨/삭제)"], key="admin_action_radio"
            )

            if action == "새 추첨 만들기":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", min_value=1, value=1, key="new_num_winners")
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], horizontal=True, key="new_draw_type")

                if draw_type == "예약 추첨":
                    date = st.date_input("추첨 날짜", value=datetime.date.today(), key="new_draw_date")
                    tm = st.time_input("추첨 시간", value=(datetime.datetime.now()+datetime.timedelta(minutes=5)).time(), key="new_draw_time")
                    draw_time = datetime.datetime.combine(date, tm)
                else:
                    draw_time = datetime.datetime.now()

                participants_txt = st.text_area("참가자 명단 (한 줄에 한 명)", key="new_participants")
                if st.button("✅ 추첨 생성", key="create_button"):
                    names = [n.strip() for n in participants_txt.split('\n') if n.strip()]
                    if not title or not names:
                        st.warning("제목과 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time <= datetime.datetime.now():
                        st.error("예약 시간은 현재 시간 이후여야 합니다.")
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
                        add_log(conn, lid, f"추첨 생성됨 (방식: {draw_type}, 참가자: {len(names)}명)")
                        st.success("추첨 생성 완료!")
                        time.sleep(1)
                        st.experimental_rerun()

            else:
                st.subheader("기존 추첨 관리")
                try:
                    df = pd.read_sql("SELECT id, title, status FROM lotteries ORDER BY id DESC", conn)
                except:
                    df = pd.DataFrame()
                if df.empty:
                    st.info("관리할 추첨이 없습니다.")
                else:
                    choice = st.selectbox("관리할 추첨 선택", df['title'], key="manage_choice")
                    sel = df[df['title']==choice].iloc[0]
                    lid = int(sel['id'])
                    if sel['status']=='completed':
                        st.write(f"**'{choice}' 재추첨**")
                        all_p = pd.read_sql("SELECT name FROM participants WHERE lottery_id=?", conn, params=(lid,))['name'].tolist()
                        prev_w = pd.read_sql("SELECT winner_name FROM winners WHERE lottery_id=?", conn, params=(lid,))['winner_name'].tolist()
                        cand = [p for p in all_p if p not in prev_w]
                        if cand:
                            chosen = st.multiselect("재추첨 후보자", options=cand, default=cand, key="redraw_candidates")
                            num_r = st.number_input("추가 당첨 인원", min_value=1, max_value=len(chosen), value=1, key="redraw_num_winners")
                            if st.button("🚀 재추첨 실행", key="redraw_button"):
                                run_draw(conn, lid, num_r, chosen)
                                st.success("재추첨 완료!")
                                time.sleep(1)
                                st.experimental_rerun()
                        else:
                            st.warning("재추첨 대상이 없습니다.")
                    st.markdown("---")
                    st.write(f"**'{choice}' 삭제**")
                    if st.button("🗑️ 삭제", key="delete_button"):
                        st.session_state.delete_confirm_id = lid
                    if st.session_state.delete_confirm_id==lid:
                        st.warning("영구 삭제 시 복구할 수 없습니다. 정말 삭제하시겠습니까?")
                        if st.button("예, 삭제합니다", key="confirm_delete_button"):
                            conn.cursor().execute("DELETE FROM lotteries WHERE id=?", (lid,))
                            conn.commit()
                            st.success("삭제되었습니다.")
                            time.sleep(1)
                            st.experimental_rerun()

    conn.close()

if __name__ == "__main__":
    main()
