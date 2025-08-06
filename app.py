import streamlit as st
import sqlite3
import random
import time
import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- 1. 설정 및 데이터베이스 초기화 ---

ADMIN_PASSWORD = "10293847"

# 데이터베이스 연결 및 테이블 구조 변경/생성
def setup_database():
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS lotteries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            draw_time TIMESTAMP NOT NULL,
            num_winners INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            name TEXT NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            winner_name TEXT NOT NULL,
            draw_round INTEGER NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS lottery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_message TEXT NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id)
        )
    ''')
    conn.commit()
    return conn

# 로그 추가 헬퍼 함수
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message) VALUES (?, ?)", (lottery_id, message))
    conn.commit()

# --- 2. 자동/수동 추첨 로직 ---

def run_draw(conn, lottery_id, num_to_draw, candidates):
    actual_num_winners = min(num_to_draw, len(candidates))
    if actual_num_winners <= 0:
        return []
    
    winners = random.sample(candidates, k=actual_num_winners)
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    max_round = c.fetchone()[0]
    current_round = (max_round or 0) + 1

    for winner in winners:
        c.execute("INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)",
                  (lottery_id, winner, current_round))
    
    c.execute("UPDATE lotteries SET status = 'completed' WHERE id = ?", (lottery_id,))
    conn.commit()
    
    log_message = f"{current_round}회차 추첨 진행. (당첨자: {', '.join(winners)})"
    add_log(conn, lottery_id, log_message)
    return winners

def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?", (now,))
    scheduled_lotteries = c.fetchall()

    for lottery_id, num_winners in scheduled_lotteries:
        c.execute("SELECT name FROM participants WHERE lottery_id = ?", (lottery_id,))
        participants = [row[0] for row in c.fetchall()]
        if participants:
            winners = run_draw(conn, lottery_id, num_winners, participants)
            if winners:
                st.session_state[f'celebrated_{lottery_id}'] = True

# --- 3. Streamlit UI 구성 ---

def main():
    st.set_page_config(page_title="NEW LOTTERY", page_icon="📜", layout="wide")
    st_autorefresh(interval=5000, limit=None, key="main_refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    st.title("📜 NEW LOTTERY")
    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.header("🎉 추첨 현황판")
        st.markdown("이 페이지는 최신 상태를 반영합니다.")
        
        try:
            lotteries_df = pd.read_sql("SELECT id, title, draw_time, status, num_winners FROM lotteries ORDER BY id DESC", conn)
        except Exception:
            st.info("아직 생성된 추첨이 없습니다.")
            lotteries_df = pd.DataFrame()

        if lotteries_df.empty:
            st.info("아직 생성된 추첨이 없습니다. 관리자 메뉴에서 추첨을 만들어주세요.")
        else:
            for index, row in lotteries_df.iterrows():
                lottery_id, title, status = row['id'], row['title'], row['status']
                draw_time = pd.to_datetime(row['draw_time'])

                with st.container(border=True):
                    st.subheader(f"✨ {title}")
                    
                    winners_df = pd.read_sql("SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round", conn, params=(lottery_id,))
                    if not winners_df.empty:
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S')})")
                        for round_num, group in winners_df.groupby('draw_round'):
                            round_text = f"{round_num}회차" if round_num == 1 else f"{round_num}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {round_text} 당첨자")
                            winner_tags = " &nbsp; ".join([f"<span style='background-color:#E8F5E9; color:#1E8E3E; border-radius:5px; padding:5px 10px; font-weight:bold;'>{name}</span>" for name in group['winner_name']])
                            st.markdown(f"<p style='text-align:center; font-size: 20px;'>{winner_tags}</p>", unsafe_allow_html=True)

                        if st.session_state.get(f'celebrated_{lottery_id}', False):
                            st.balloons()
                            st.session_state[f'celebrated_{lottery_id}'] = False
                    
                    else:
                        time_diff = draw_time - datetime.datetime.now()
                        if time_diff.total_seconds() > 0:
                            countdown_text = str(time_diff).split('.')[0]
                            st.info(f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S')} (남은 시간: {countdown_text})")
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 추첨이 자동으로 진행됩니다...")
                    
                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        participants_df = pd.read_sql("SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lottery_id,))
                        st.dataframe(participants_df.rename(columns={'name': '이름'}), use_container_width=True, height=150)
                    with tab2:
                        logs_df = pd.read_sql("SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp, 'localtime') as '시간', log_message as '내용' FROM lottery_logs WHERE lottery_id = ? ORDER BY id", conn, params=(lottery_id,))
                        st.dataframe(logs_df, use_container_width=True, height=150)

    with col2:
        st.header("👑 추첨 관리자 메뉴")
        if 'admin_auth' not in st.session_state:
            st.session_state['admin_auth'] = False

        if not st.session_state['admin_auth']:
            password = st.text_input("관리자 코드를 입력하세요.", type="password", key="admin_pw")
            if st.button("인증"):
                if password == ADMIN_PASSWORD:
                    st.session_state['admin_auth'] = True
                    st.rerun()
                else:
                    st.error("코드가 올바르지 않습니다.")
        
        if st.session_state['admin_auth']:
            st.success("관리자로 인증되었습니다.")
            
            admin_action = st.radio("작업 선택", ["새 추첨 만들기", "기존 추첨 관리 (재추첨 등)"], key="admin_action")

            if admin_action == "새 추첨 만들기":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", 1, value=1, key="new_num_winners")
                
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], horizontal=True, key="new_draw_type")
                
                draw_time = None
                if draw_type == "예약 추첨":
                    # 안전하고 간단한 시간 계산 로직으로 수정됨
                    default_time = datetime.datetime.now() + datetime.timedelta(minutes=5)
                    draw_time = st.datetime_input(
                        "추첨 시간", 
                        value=default_time, 
                        min_value=datetime.datetime.now(), # 과거 시간 선택 방지
                        key="new_draw_time"
                    )
                
                participants_text = st.text_area("참가자 명단 (한 줄에 한 명, 중복 가능)", key="new_participants")
                
                if st.button("✅ 추첨 생성", type="primary"):
                    participants = [name.strip() for name in participants_text.split('\n') if name.strip()]
                    if not title or not participants:
                        st.warning("제목과 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time <= datetime.datetime.now():
                        st.error("예약 시간은 현재 시간 이후여야 합니다.")
                    else:
                        final_draw_time = draw_time if draw_type == "예약 추첨" else datetime.datetime.now()
                        c = conn.cursor()
                        c.execute("INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')",
                                  (title, final_draw_time, num_winners))
                        lottery_id = c.lastrowid
                        for p_name in participants:
                            c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lottery_id, p_name))
                        conn.commit()
                        add_log(conn, lottery_id, f"추첨 생성됨 (방식: {draw_type}, 총 참가자: {len(participants)}명)")
                        st.success("추첨이 생성되었습니다!")
                        time.sleep(1); st.rerun()
            
            elif admin_action == "기존 추첨 관리 (재추첨 등)":
                st.subheader("기존 추첨 관리")
                # 'lotteries_df' 변수가 로드 되었는지 확인 후 진행
                if 'lotteries_df' in locals() and not lotteries_df.empty:
                    choice = st.selectbox("관리할 추첨 선택", options=lotteries_df['title'], key="manage_choice")
                    selected_lottery = lotteries_df[lotteries_df['title'] == choice].iloc[0]
                    lottery_id = int(selected_lottery['id'])

                    if selected_lottery['status'] == 'completed':
                        st.markdown("---")
                        st.write(f"**'{choice}' 재추첨**")

                        all_participants = pd.read_sql("SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lottery_id,))['name'].tolist()
                        prev_winners = pd.read_sql("SELECT winner_name FROM winners WHERE lottery_id = ?", conn, params=(lottery_id,))['winner_name'].tolist()
                        
                        candidates = [p for p in all_participants if p not in prev_winners]
                        
                        if not candidates:
                            st.warning("재추첨할 수 있는 후보가 없습니다.")
                        else:
                            st.write("아래 명단에서 재추첨 대상을 선택하세요. (이미 당첨된 사람은 제외되었습니다)")
                            final_candidates = st.multiselect("재추첨 후보자", options=list(set(candidates)), default=list(set(candidates)), key="redraw_candidates")
                            num_redraw_winners = st.number_input("추가 당첨 인원", min_value=1, max_value=len(final_candidates) if final_candidates else 1, value=1, key="redraw_num_winners")

                            if st.button("🚀 재추첨 실행", type="primary"):
                                if not final_candidates:
                                    st.error("재추첨 후보가 없습니다.")
                                else:
                                    run_draw(conn, lottery_id, num_redraw_winners, final_candidates)
                                    st.success("재추첨이 완료되었습니다!")
                                    time.sleep(1); st.rerun()

                    else:
                        st.info("아직 추첨이 완료되지 않아 재추첨할 수 없습니다.")
                else:
                    st.info("관리할 추첨이 없습니다.")

    conn.close()

if __name__ == "__main__":
    main()
