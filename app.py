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
    """현재 시간을 한국 시간대(KST)로 반환하는 함수"""
    return datetime.datetime.now(KST)

# --- 데이터베이스 초기화 ---
def setup_database():
    conn = sqlite3.connect(
        'lottery_data_v2.db', check_same_thread=False,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.executescript('''
    CREATE TABLE IF NOT EXISTS lotteries (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, draw_time timestamp, num_winners INTEGER,
        status TEXT, created_at timestamp DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY, lottery_id INTEGER, name TEXT NOT NULL,
        FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS winners (
        id INTEGER PRIMARY KEY, lottery_id INTEGER, winner_name TEXT, draw_round INTEGER,
        FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS lottery_logs (
        id INTEGER PRIMARY KEY, lottery_id INTEGER, log_timestamp timestamp DEFAULT CURRENT_TIMESTAMP,
        log_message TEXT, FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    ''')
    conn.commit()
    return conn

# --- 헬퍼 함수 및 추첨 로직 ---
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute(
        "INSERT INTO lottery_logs (lottery_id, log_message, log_timestamp) VALUES (?, ?, ?)",
        (lottery_id, message, now_kst())
    )
    conn.commit()


def run_draw(conn, lottery_id, num_to_draw, candidates):
    actual = min(num_to_draw, len(candidates))
    if actual <= 0:
        return []
    winners = random.sample(candidates, k=actual)
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    prev_round = c.fetchone()[0] or 0
    current_round = prev_round + 1
    for w in winners:
        c.execute(
            "INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)",
            (lottery_id, w, current_round)
        )
    # 상태 업데이트는 최초 또는 마지막 회차 후 수행
    c.execute("UPDATE lotteries SET status='completed' WHERE id=?", (lottery_id,))
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 진행. 당첨자: {', '.join(winners)}")
    return winners


def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    c.execute(
        "SELECT id, num_winners, title FROM lotteries WHERE status='scheduled' AND draw_time <= ?",
        (now_kst(),)
    )
    for lid, num, title in c.fetchall():
        participants = c.execute(
            "SELECT name FROM participants WHERE lottery_id=?", (lid,)
        ).fetchall()
        all_participants = [r[0] for r in participants]
        if all_participants:
            winners = run_draw(conn, lid, num, all_participants)
            if winners:
                st.session_state[f'celebrated_{lid}'] = True

# --- Streamlit UI (수정버전) ---
def main():
    st.set_page_config(page_title="NEW LOTTERY", page_icon="📜", layout="wide")
    st_autorefresh(interval=2000, limit=None, key="refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    # 세션 상태 초기화
    st.session_state.setdefault('admin_auth', False)
    st.session_state.setdefault('delete_confirm_id', None)

    st.title("📜 모두가 함께 보는 실시간 추첨")
    col1, col2 = st.columns([2, 1])

    # 좌측: 통합 추첨 현황판
    with col1:
        st.header("🎉 추첨 타임라인")
        lotteries_df = pd.read_sql(
            "SELECT id, title, draw_time, status FROM lotteries ORDER BY id DESC",
            conn, parse_dates=['draw_time']
        )
        if lotteries_df.empty:
            st.info("생성된 추첨이 없습니다. 관리자 메뉴에서 추첨을 만들어주세요.")
        else:
            for _, row in lotteries_df.iterrows():
                lid = int(row['id'])
                title, status, draw_time = row['title'], row['status'], row['draw_time']
                if draw_time.tzinfo is None:
                    draw_time = draw_time.replace(tzinfo=KST)
                with st.container():
                    st.subheader(f"✨ {title}")
                    # 상태별 표시
                    if status == 'completed':
                        st.success(
                            f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')})"
                        )
                        winners_df = pd.read_sql(
                            "SELECT winner_name, draw_round FROM winners WHERE lottery_id=? ORDER BY draw_round",
                            conn, params=(lid,), index_col=None
                        )
                        for round_num, grp in winners_df.groupby('draw_round'):
                            label = f"{round_num}회차" if round_num == 1 else f"{round_num}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {label} 당첨자")
                            tags = ' &nbsp; '.join([
                                f"<span style='background-color:#E8F5E9; color:#1E8E3E;"
                                f" border-radius:5px; padding:5px 10px; font-weight:bold;'>{n}</span>"
                                for n in grp['winner_name']
                            ])
                            st.markdown(f"<p style='text-align:center; font-size:20px;'>{tags}</p>", unsafe_allow_html=True)
                        if st.session_state.pop(f'celebrated_{lid}', False):
                            st.balloons()
                    else:
                        diff = draw_time - now_kst()
                        if diff.total_seconds() > 0:
                            st.info(
                                f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')} "
                                f"(남은 시간: {str(diff).split('.')[0]})"
                            )
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 자동으로 진행됩니다...")
                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        parts = pd.read_sql(
                            "SELECT name FROM participants WHERE lottery_id = ?",
                            conn, params=(lid,)
                        )
                        st.dataframe(parts.rename(columns={'name': '이름'}), use_container_width=True, height=150)
                    with tab2:
                        logs = pd.read_sql(
                            "SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp) AS 시간, log_message AS 내용"
                            " FROM lottery_logs WHERE lottery_id=? ORDER BY id",
                            conn, params=(lid,)
                        )
                        st.dataframe(logs, use_container_width=True, height=150)

    # 우측: 관리자 메뉴
    with col2:
        st.header("👑 관리자 메뉴")
        if not st.session_state['admin_auth']:
            pw = st.text_input("관리자 코드", type="password", key="admin_pw")
            if st.button("인증"):
                if pw == st.secrets.get("admin", {}).get("password", None):
                    st.session_state['admin_auth'] = True
                    st.experimental_rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
        else:
            st.success("관리자 모드 활성화")
            action = st.radio("작업 선택", ["새 추첨 만들기", "기존 추첨 관리"], key="admin_action_radio")
            if action == "새 추첨 만들기":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", 1, value=1, key="new_num_winners")
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], horizontal=True)
                if draw_type == "예약 추첨":
                    col_date, col_time = st.columns(2)
                    with col_date:
                        date = st.date_input("날짜", value=now_kst().date(), key="new_draw_date")
                    with col_time:
                        tm = st.time_input("시간 (HH:MM)", value=(now_kst() + datetime.timedelta(minutes=5)).time(), key="new_draw_time")
                    # 타임존 정보 포함
                    draw_time_to_set = datetime.datetime.combine(date, tm).replace(tzinfo=KST)
                else:
                    draw_time_to_set = now_kst()
                participants_txt = st.text_area("참가자 명단 (한 줄에 한 명씩)", key="new_participants", height=150)
                if st.button("✅ 추첨 생성", key="create_button", type="primary"):
                    names = [n.strip() for n in participants_txt.splitlines() if n.strip()]
                    if not title or not names:
                        st.warning("제목과 최소 한 명 이상의 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time_to_set <= now_kst():
                        st.error("예약 시간은 현재 시간 이후여야 합니다.")
                    else:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO lotteries (title, draw_time, num_winners, status)VALUES (?, ?, ?, 'scheduled')",
                            (title, draw_time_to_set, num_winners)
                        )
                        lid = c.lastrowid
                        for n in names:
                            c.execute(
                                "INSERT INTO participants (lottery_id, name) VALUES (?, ?)",
                                (lid, n)
                            )
                        conn.commit()
                        add_log(conn, lid, f"추첨 생성 (방식: {draw_type}, 참가자 수: {len(names)})")
                        st.success("추첨이 성공적으로 생성되었습니다.")
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
                    if sel['status'] == 'completed':
                        st.write("**재추첨**")
                        all_p = pd.read_sql(
                            "SELECT name FROM participants WHERE lottery_id=?", conn, params=(lid,)
                        )['name'].tolist()
                        prev_w = pd.read_sql(
                            "SELECT winner_name FROM winners WHERE lottery_id=?", conn, params=(lid,)
                        )['winner_name'].tolist()
                        candidates = [p for p in all_p if p not in prev_w]
                        if candidates:
                            chosen = st.multiselect("재추첨 대상자", candidates, default=candidates, key=f"redraw_cand_{lid}")
                            num_redraw = st.number_input("추첨 인원", 1, len(chosen), 1, key=f"redraw_num_{lid}")
                            if st.button("🚀 재추첨 실행", key=f"redraw_btn_{lid}"):
                                run_draw(conn, lid, num_redraw, chosen)
                                st.success("재추첨 완료")
                                time.sleep(1)
                                st.experimental_rerun()
                        else:
                            st.warning("재추첨 대상이 없습니다.")
                    st.markdown("---")
                    st.write("**추첨 삭제**")
                    if st.button("🗑️ 이 추첨 삭제하기", key=f"delete_btn_{lid}"):
                        st.session_state['delete_confirm_id'] = lid
                        st.experimental_rerun()
                    if st.session_state.get('delete_confirm_id') == lid:
                        st.warning(f"**경고**: '{sel['title']}'의 모든 기록이 삭제됩니다.")
                        if st.button("예, 정말로 삭제합니다", key=f"confirm_del_{lid}"):
                            c = conn.cursor()
                            c.execute("DELETE FROM lotteries WHERE id=?", (lid,))
                            conn.commit()
                            st.success("삭제되었습니다.")
                            st.session_state['delete_confirm_id'] = None
                            time.sleep(1)
                            st.experimental_rerun()
    conn.close()

if __name__ == '__main__':
    main()
