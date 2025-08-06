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

# --- 1. 설정 및 데이터베이스 초기화 ---
def setup_database():
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.execute('''
        CREATE TABLE IF NOT EXISTS lotteries (id INTEGER PRIMARY KEY, title TEXT NOT NULL, draw_time TIMESTAMP, num_winners INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (id INTEGER PRIMARY KEY, lottery_id INTEGER, name TEXT NOT NULL, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS winners (id INTEGER PRIMARY KEY, lottery_id INTEGER, winner_name TEXT, draw_round INTEGER, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS lottery_logs (id INTEGER PRIMARY KEY, lottery_id INTEGER, log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, log_message TEXT, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    # ================== 재추첨 예약을 위한 새 테이블 추가 ==================
    c.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_redraws (
            id INTEGER PRIMARY KEY,
            lottery_id INTEGER NOT NULL,
            execution_time TIMESTAMP NOT NULL,
            num_winners INTEGER NOT NULL,
            candidates TEXT NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
        )
    ''')
    # =================================================================
    conn.commit()
    return conn

# --- 2. 헬퍼 및 로직 함수 ---
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message, log_timestamp) VALUES (?, ?, ?)", (lottery_id, message, now_kst()))
    conn.commit()

def run_draw(conn, lottery_id, num_to_draw, candidates):
    actual = min(num_to_draw, len(candidates))
    if actual <= 0: return []
    winners = random.sample(candidates, k=actual)
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    prev = c.fetchone()[0] or 0
    current_round = prev + 1
    for w in winners:
        c.execute("INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)",(lottery_id, w, current_round))
    # 1회차 추첨(새 추첨)일 때만 상태를 'completed'로 변경
    if current_round == 1:
        c.execute("UPDATE lotteries SET status = 'completed' WHERE id = ?", (lottery_id,))
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 진행. (당첨자: {', '.join(winners)})")
    return winners

def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    now = now_kst()
    c.execute("SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?", (now,))
    for lottery_id, num_winners in c.fetchall():
        c.execute("SELECT name FROM participants WHERE lottery_id = ?", (lottery_id,))
        participants = [r[0] for r in c.fetchall()]
        if participants:
            winners = run_draw(conn, lottery_id, num_winners, participants)
            if winners:
                st.session_state[f'celebrated_{lottery_id}'] = True

# ================== 예약된 재추첨을 실행하는 함수 추가 ==================
def check_and_run_scheduled_redraws(conn):
    c = conn.cursor()
    now = now_kst()
    # 실행 시간이 된 재추첨 작업을 가져옴
    c.execute("SELECT id, lottery_id, num_winners, candidates FROM scheduled_redraws WHERE execution_time <= ?", (now,))
    tasks_to_run = c.fetchall()

    for task_id, lottery_id, num_winners, candidates_str in tasks_to_run:
        candidates = candidates_str.split(',') # 저장된 후보자 명단을 리스트로 변환
        if candidates:
            # 기존의 안정적인 run_draw 함수를 그대로 사용
            winners = run_draw(conn, lottery_id, num_winners, candidates)
            if winners:
                st.session_state[f'celebrated_{lottery_id}'] = True
        
        # 실행된 작업은 대기열에서 삭제
        c.execute("DELETE FROM scheduled_redraws WHERE id = ?", (task_id,))
        conn.commit()
# ====================================================================

# --- 3. Streamlit UI 구성 ---
def main():
    st.set_page_config(page_title="new lottery", page_icon="📜", layout="wide")
    st_autorefresh(interval=1000, limit=None, key="main_refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)
    check_and_run_scheduled_redraws(conn) # 예약 재추첨 확인 함수 호출

    st.session_state.setdefault('admin_auth', False)
    st.session_state.setdefault('delete_confirm_id', None)

    st.title("📜 NEW LOTTERY")
    st.markdown("---")
    col1, col2 = st.columns([2, 1])

    # 추첨 현황판 (사용자 제공 버전과 동일)
    with col1:
        st.header("🎉 추첨 현황판")
        st.markdown("이 페이지는 최신 상태를 반영합니다.")
        try:
            df_lot = pd.read_sql("SELECT * FROM lotteries ORDER BY id DESC", conn)
        except:
            df_lot = pd.DataFrame()

        if df_lot.empty:
            st.info("아직 생성된 추첨이 없습니다.")
        else:
            for _, row in df_lot.iterrows():
                lid, title, status = int(row['id']), row['title'], row['status']
                raw = row['draw_time']
                if isinstance(raw, str):
                    draw_time = datetime.datetime.fromisoformat(raw)
                else:
                    draw_time = raw
                if hasattr(draw_time, 'tzinfo') and draw_time.tzinfo is None:
                    draw_time = draw_time.replace(tzinfo=KST)
                with st.container(border=True):
                    st.subheader(f"✨ {title}")
                    winners_df = pd.read_sql("SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round", conn, params=(lid,))
                    if not winners_df.empty:
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S')})")
                        for rnd, grp in winners_df.groupby('draw_round'):
                            label = '1회차' if rnd == 1 else f"{rnd}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {label} 당첨자")
                            tags = " &nbsp; ".join([f"<span style='background-color:#E8F5E9; color:#1E8E3E; border-radius:5px; padding:5px 10px; font-weight:bold;'>{n}</span>" for n in grp['winner_name']])
                            st.markdown(f"<p style='text-align:center; font-size:20px;'>{tags}</p>", unsafe_allow_html=True)
                        if st.session_state.get(f'celebrated_{lid}', False):
                            st.balloons(); st.session_state[f'celebrated_{lid}'] = False
                    else:
                        diff = draw_time - now_kst()
                        if diff.total_seconds() > 0:
                            st.info(f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S')} (남은 시간: {str(diff).split('.')[0]})")
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 자동 진행됩니다...")
                    
                    # 예약된 재추첨 정보 표시
                    redraw_tasks = pd.read_sql("SELECT execution_time, num_winners FROM scheduled_redraws WHERE lottery_id=?", conn, params=(lid,))
                    for _, task in redraw_tasks.iterrows():
                        rt = task['execution_time']
                        if isinstance(rt, str): rt = datetime.datetime.fromisoformat(rt)
                        if rt.tzinfo is None: rt = rt.replace(tzinfo=KST)
                        st.info(f"**재추첨 예약됨:** {rt.strftime('%Y-%m-%d %H:%M:%S')} ({task['num_winners']}명)")

                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        part_df = pd.read_sql("SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lid,))
                        st.dataframe(part_df.rename(columns={'name':'이름'}), use_container_width=True, height=150)
                    with tab2:
                        log_df = pd.read_sql("SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp, 'localtime') AS 시간, log_message AS 내용 FROM lottery_logs WHERE lottery_id = ? ORDER BY id", conn, params=(lid,))
                        st.dataframe(log_df, use_container_width=True, height=150)

    # 관리자 메뉴
    with col2:
        st.header("👑 추첨 관리자")
        if not st.session_state.admin_auth:
            pw = st.text_input("관리자 코드", type="password", key="admin_pw_input")
            if st.button("인증", key="auth_button"):
                if pw == st.secrets.get('admin', {}).get('password'):
                    st.session_state.admin_auth = True; st.experimental_rerun()
                else:
                    st.error("코드가 올바르지 않습니다.")
        else:
            st.success("관리자로 인증됨")
            action = st.radio("작업 선택", ["새 추첨 생성", "기존 추첨 관리"], key="admin_action_radio")

            if action == "새 추첨 생성":
                # 이 부분은 사용자 제공 버전과 100% 동일
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", min_value=1, value=1, key="new_num_winners")
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], key="new_draw_type", horizontal=True)
                if draw_type == "예약 추첨":
                    date = st.date_input("날짜", value=now_kst().date(), key="new_draw_date")
                    tm = st.time_input("시간 (HH:MM)", value=(now_kst() + datetime.timedelta(minutes=5)).time(), step=datetime.timedelta(minutes=1), key="new_draw_time")
                    draw_time = datetime.datetime.combine(date, tm, tzinfo=KST)
                else:
                    draw_time = now_kst()
                participants_txt = st.text_area("참가자 명단 (한 줄에 한 명)", key="new_participants", height=150)
                if st.button("✅ 추첨 생성", key="create_button", type="primary"):
                    names = [n.strip() for n in participants_txt.split('\n') if n.strip()]
                    if not title or not names: st.warning("제목과 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time <= now_kst(): st.error("예약 시간은 현재 이후여야 합니다.")
                    else:
                        c = conn.cursor()
                        c.execute("INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')", (title, draw_time, num_winners))
                        lid = c.lastrowid
                        for n in names: c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lid, n))
                        conn.commit()
                        add_log(conn, lid, f"추첨 생성 (방식: {draw_type}, 참가자 수: {len(names)})")
                        st.success("추첨 생성 완료"); time.sleep(1); st.experimental_rerun()
            else:
                st.subheader("기존 추첨 관리")
                df_m = pd.read_sql("SELECT id, title, status FROM lotteries ORDER BY id DESC", conn)
                if df_m.empty:
                    st.info("관리할 추첨이 없습니다.")
                else:
                    choice = st.selectbox("추첨 선택", df_m['title'], key="manage_choice")
                    sel = df_m[df_m['title']==choice].iloc[0]
                    lid = int(sel['id'])
                    
                    if sel['status']=='completed':
                        st.write("**재추첨**")
                        all_p = pd.read_sql("SELECT name FROM participants WHERE lottery_id=?", conn, params=(lid,))['name'].tolist()
                        prev = pd.read_sql("SELECT winner_name FROM winners WHERE lottery_id=?", conn, params=(lid,))['winner_name'].tolist()
                        cand = list(all_p)
                        for winner in prev:
                            if winner in cand: cand.remove(winner)
                        
                        if cand:
                            # ================== 재추첨 예약 기능 추가 ==================
                            redraw_type = st.radio("재추첨 방식", ["즉시 추첨", "예약 추첨"], key=f"redraw_type_{lid}", horizontal=True)

                            redraw_time = now_kst()
                            if redraw_type == "예약 추첨":
                                redraw_date = st.date_input("재추첨 날짜", value=now_kst().date(), key=f"redraw_date_{lid}")
                                redraw_tm = st.time_input("재추첨 시간", value=(now_kst() + datetime.timedelta(minutes=5)).time(), step=datetime.timedelta(minutes=1), key=f"redraw_time_{lid}")
                                redraw_time = datetime.datetime.combine(redraw_date, redraw_tm, tzinfo=KST)

                            chosen = st.multiselect("재추첨 후보자", cand, default=cand, key=f"redraw_cand_{lid}")
                            num_r = st.number_input("추첨 인원 수", 1, len(chosen) if chosen else 1, 1, key=f"redraw_num_{lid}")
                            
                            if st.button("🚀 재추첨 실행/예약", key=f"redraw_btn_{lid}", type="primary"):
                                if not chosen: st.warning("재추첨 후보자를 선택하세요.")
                                elif redraw_type == "예약 추첨" and redraw_time <= now_kst(): st.error("예약 시간은 현재 이후여야 합니다.")
                                else:
                                    if redraw_type == "즉시 추첨":
                                        run_draw(conn, lid, num_r, chosen)
                                        st.success("재추첨 완료"); time.sleep(1); st.experimental_rerun()
                                    else: # 예약 추첨
                                        # '작업 대기열'에 추가
                                        c = conn.cursor()
                                        candidates_str = ",".join(chosen) # 후보자 목록을 문자열로 변환
                                        c.execute("INSERT INTO scheduled_redraws (lottery_id, execution_time, num_winners, candidates) VALUES (?, ?, ?, ?)",
                                                  (lid, redraw_time, num_r, candidates_str))
                                        conn.commit()
                                        add_log(conn, lid, f"재추첨 예약됨 ({redraw_time.strftime('%Y-%m-%d %H:%M')}, {len(chosen)}명 대상)")
                                        st.success("재추첨이 예약되었습니다."); time.sleep(1); st.experimental_rerun()
                            # =======================================================
                        else:
                            st.warning("재추첨 후보가 없습니다.")
                            
                    st.markdown("---")
                    # 삭제 로직 (사용자 제공 버전과 동일)
                    if st.button("삭제", key=f"delete_btn_{lid}"):
                        st.session_state.delete_confirm_id = lid
                    if st.session_state.delete_confirm_id == lid:
                        st.warning("정말 삭제하시겠습니까?")
                        if st.button("예, 삭제합니다", key=f"confirm_del_btn_{lid}", type="primary"):
                            c = conn.cursor()
                            c.execute("DELETE FROM lotteries WHERE id=?", (lid,)); conn.commit()
                            st.success("삭제 완료"); time.sleep(1); st.experimental_rerun()

    conn.close()

if __name__ == "__main__":
    main()
