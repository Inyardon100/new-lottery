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
    """현재 시간을 한국 시간대(KST)로 반환"""
    return datetime.datetime.now(KST)

# --- DB 초기화 ---

def setup_database():
    conn = sqlite3.connect(
        'lottery_data_v2.db', check_same_thread=False,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.executescript('''
    CREATE TABLE IF NOT EXISTS lotteries (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, draw_time TIMESTAMP, num_winners INTEGER,
        status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        id INTEGER PRIMARY KEY, lottery_id INTEGER, log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        log_message TEXT, FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
    );
    ''')
    conn.commit()
    return conn

# --- 로깅 ---
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute(
        "INSERT INTO lottery_logs (lottery_id, log_message, log_timestamp) VALUES (?, ?, ?)",
        (lottery_id, message, now_kst())
    )
    conn.commit()

# --- 추첨 로직 ---
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
    c.execute(
        "UPDATE lotteries SET status = 'completed' WHERE id = ?",
        (lottery_id,)
    )
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 완료: {', '.join(winners)}")
    return winners

# --- 예약 추첨 자동 실행 ---
def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    c.execute(
        "SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?",
        (now_kst(),)
    )
    for lid, num in c.fetchall():
        participants = c.execute(
            "SELECT name FROM participants WHERE lottery_id = ?", (lid,)
        ).fetchall()
        names = [r[0] for r in participants]
        if names:
            winners = run_draw(conn, lid, num, names)
            if winners:
                st.session_state[f"celebrated_{lid}"] = True

# --- 스트림릿 UI ---
def main():
    st.set_page_config(page_title = "NEW LOTTERY", layout = "wide")
    st_autorefresh(interval = 2000, limit = None, key = "refresher")

    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    # 세션 초기화
    if 'admin_auth' not in st.session_state:
        st.session_state['admin_auth'] = False
    if 'delete_confirm_id' not in st.session_state:
        st.session_state['delete_confirm_id'] = None

    st.title("📜 모두가 함께 보는 실시간 추첨")
    col1, col2 = st.columns([2,1])

    # 좌측: 추첨 현황
    with col1:
        st.header("🎉 추첨 타임라인")
        df = pd.read_sql(
            "SELECT id, title, draw_time, status FROM lotteries ORDER BY id DESC", conn,
            parse_dates = ['draw_time']
        )
        if df.empty:
            st.info("생성된 추첨이 없습니다.")
        else:
            for _, row in df.iterrows():
                lid = int(row['id'])
                title = row['title']
                status = row['status']
                draw_time = row['draw_time']
                if draw_time.tzinfo is None:
                    draw_time = draw_time.replace(tzinfo = KST)
                with st.container():
                    st.subheader(f"✨ {title}")

                    if status == 'completed':
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')})")
                        winners_df = pd.read_sql(
                            "SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round",
                            conn, params = (lid,)
                        )
                        for rnd, group in winners_df.groupby('draw_round'):
                            label = f"{rnd}회차" + (" (재추첨)" if rnd > 1 else "")
                            st.markdown(f"#### 🏆 {label} 당첨자")
                            tags = ' '.join([f"`{n}`" for n in group['winner_name']])
                            st.markdown(tags)
                        if st.session_state.pop(f"celebrated_{lid}", False):
                            st.balloons()
                    else:
                        diff = draw_time - now_kst()
                        if diff.total_seconds() > 0:
                            st.info(
                                f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                                f" (남은 시간: {str(diff).split('.')[0]})"
                            )
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 자동으로 진행됩니다...")

                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        parts_df = pd.read_sql(
                            "SELECT name FROM participants WHERE lottery_id = ?", conn, params = (lid,)
                        )
                        st.dataframe(parts_df.rename(columns = {'name':'이름'}), height=150)
                    with tab2:
                        logs_df = pd.read_sql(
                            "SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp) AS 시간, log_message AS 내용 "
                            "FROM lottery_logs WHERE lottery_id = ? ORDER BY id",
                            conn, params = (lid,)
                        )
                        st.dataframe(logs_df, height=150)

    # 우측: 관리자 메뉴
    with col2:
        st.header("👑 관리자 메뉴")
        if not st.session_state['admin_auth']:
            pw = st.text_input("관리자 코드", type = "password")
            if st.button("인증"):
                if pw == st.secrets['admin']['password']:
                    st.session_state['admin_auth'] = True
                    st.experimental_rerun()
                else:
                    st.error("관리자 코드가 올바르지 않습니다.")
        else:
            action = st.radio("작업 선택", ["새 추첨 만들기", "기존 추첨 관리"])

            if action == "새 추첨 만들기":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목")
                num_winners = st.number_input("당첨 인원 수", min_value=1, value=1)
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"])

                # 예약 추첨 입력
                if draw_type == "예약 추첨":
                    # 키에 의해 자동 저장되므로 기본값 지정 불필요
                    date = st.date_input("날짜", key="new_draw_date")
                    tm = st.time_input("시간", step = datetime.timedelta(minutes=1), key="new_draw_time")
                    draw_dt = datetime.datetime.combine(date, tm).replace(tzinfo = KST)
                else:
                    draw_dt = now_kst()

                participants_txt = st.text_area("참가자 명단 (한 줄에 한 명씩)")
                if st.button("✅ 추첨 생성"):
                    names = [n.strip() for n in participants_txt.splitlines() if n.strip()]
                    if not title or not names:
                        st.warning("제목과 최소 한 명 이상의 참가자가 필요합니다.")
                    elif draw_type == "예약 추첨" and draw_dt <= now_kst():
                        st.error("예약 시간은 현재 시간 이후여야 합니다.")
                    else:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')",
                            (title, draw_dt, num_winners)
                        )
                        lid = c.lastrowid
                        for nm in names:
                            c.execute(
                                "INSERT INTO participants (lottery_id, name) VALUES (?, ?)",
                                (lid, nm)
                            )
                        conn.commit()
                        add_log(conn, lid, f"추첨 생성: 방식={draw_type}, 참가자={len(names)}명")
                        st.success("추첨이 성공적으로 생성되었습니다.")
                        time.sleep(1)
                        st.experimental_rerun()
            
            else:
                st.subheader("기존 추첨 관리")
                manage_df = pd.read_sql(
                    "SELECT id, title, status FROM lotteries ORDER BY id DESC", conn
                )
                if manage_df.empty:
                    st.info("관리할 추첨이 없습니다.")
                else:
                    choice = st.selectbox("추첨 선택", manage_df["title"])
                    row = manage_df[manage_df["title"] == choice].iloc[0]
                    lid = int(row["id"])

                    # 재추첨
                    if row["status"] == 'completed':
                        st.write("**재추첨**")
                        all_p = pd.read_sql(
                            "SELECT name FROM participants WHERE lottery_id = ?", conn, params = (lid,)
                        )['name'].tolist()
                        prev_w = pd.read_sql(
                            "SELECT winner_name FROM winners WHERE lottery_id = ?", conn, params = (lid,)
                        )['winner_name'].tolist()
                        candidates = [p for p in all_p if p not in prev_w]
                        if candidates:
                            chosen = st.multiselect("재추첨 대상자", candidates)
                            num_redraw = st.number_input("추첨 인원", min_value=1, max_value=len(chosen), value=1)
                            if st.button("🚀 재추첨 실행"):
                                run_draw(conn, lid, num_redraw, chosen)
                                st.success("재추첨이 완료되었습니다.")
                                time.sleep(1)
                                st.experimental_rerun()
                        else:
                            st.warning("재추첨 대상이 없습니다.")

                    # 삭제 처리
                    st.markdown("---")
                    st.write("**추첨 삭제**")
                    if st.button("🗑️ 삭제", key = f"del_{lid}"):
                        st.session_state['delete_confirm_id'] = lid

                    if st.session_state['delete_confirm_id'] == lid:
                        st.warning(f"확인: '{row['title']}' 추첨을 삭제하시겠습니까?")
                        if st.button("예, 삭제합니다", key = f"confirm_del_{lid}"):
                            try:
                                c = conn.cursor()
                                c.execute("DELETE FROM lotteries WHERE id = ?", (lid,))
                                conn.commit()
                                add_log(conn, lid, "추첨 삭제 완료")
                                st.success("추첨이 삭제되었습니다.")
                            except Exception as e:
                                st.error(f"삭제 오류: {e}")
                            time.sleep(1)
                            st.experimental_rerun()

    conn.close()

if __name__ == '__main__':
    main()
