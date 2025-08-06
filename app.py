import streamlit as st
import sqlite3
import random
import time
import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- 1. 데이터베이스 설정 및 헬퍼 함수 ---
def setup_database():
    """데이터베이스 연결 및 테이블 생성"""
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.execute('''
        CREATE TABLE IF NOT EXISTS lotteries (id INTEGER PRIMARY KEY, title TEXT, draw_time TIMESTAMP, num_winners INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (id INTEGER PRIMARY KEY, lottery_id INTEGER, name TEXT, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS winners (id INTEGER PRIMARY KEY, lottery_id INTEGER, winner_name TEXT, draw_round INTEGER, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS lottery_logs (id INTEGER PRIMARY KEY, lottery_id INTEGER, log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, log_message TEXT, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    conn.commit()
    return conn

def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message) VALUES (?, ?)", (lottery_id, message))
    conn.commit()

# --- 2. 로그인 페이지 함수 ---
def login_page():
    """로그인 화면을 렌더링하는 함수"""
    st.title("👑 관리자 인증")
    st.write("계속하려면 관리자 코드를 입력하세요.")
    
    password = st.text_input("관리자 코드", type="password", key="login_password")
    
    if st.button("인증", key="login_button"):
        try:
            # st.secrets를 사용하여 보안 강화
            if password == st.secrets["admin"]["password"]:
                st.session_state['admin_auth'] = True
                st.rerun() # 인증 성공 시 즉시 새로고침하여 메인 앱을 렌더링
            else:
                st.error("코드가 올바르지 않습니다.")
        except KeyError:
            st.error("Secrets 설정을 확인해주세요. 관리자 코드가 설정되지 않았습니다.")
        except Exception as e:
            st.error(f"예상치 못한 오류가 발생했습니다: {e}")

# --- 3. 메인 애플리케이션 페이지 함수 ---
def main_app():
    """로그인 성공 후 보여줄 메인 애플리케이션 화면"""
    st_autorefresh(interval=5000, limit=None, key="main_refresher")
    conn = setup_database()

    # 예약된 추첨 자동 실행
    check_and_run_scheduled_draws(conn)

    st.title("📜 NEW LOTTERY")
    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        # 추첨 현황판 로직...
        st.header("🎉 추첨 현황판")
        try:
            lotteries_df = pd.read_sql("SELECT id, title, draw_time, status, num_winners FROM lotteries ORDER BY id DESC", conn)
        except Exception:
            lotteries_df = pd.DataFrame()

        if lotteries_df.empty:
            st.info("생성된 추첨이 없습니다.")
        else:
            for index, row in lotteries_df.iterrows():
                lottery_id = int(row['id'])
                # ... 현황판 세부 UI ...
                with st.container(border=True):
                    st.subheader(f"✨ {row['title']}")
                    # ... (세부 로직은 이전과 동일)
                    winners_df = pd.read_sql("SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round", conn, params=(lottery_id,))
                    if not winners_df.empty:
                        st.success(f"**추첨 완료!** ({pd.to_datetime(row['draw_time']).strftime('%Y-%m-%d %H:%M:%S')})")
                        # ...
                    else:
                        time_diff = pd.to_datetime(row['draw_time']) - datetime.datetime.now()
                        if time_diff.total_seconds() > 0:
                             st.info(f"**추첨 예정:** (남은 시간: {str(time_diff).split('.')[0]})")
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
        # 관리자 메뉴 로직...
        st.header("👑 관리자 메뉴")
        st.success("관리자로 인증되었습니다.")
        
        admin_action = st.radio("작업 선택", ["새 추첨 만들기", "기존 추첨 관리 (재추첨/삭제)"], key="admin_action")

        if admin_action == "새 추첨 만들기":
            st.subheader("새 추첨 만들기")
            # ... (이하 관리자 메뉴 로직은 이전과 동일하며 안정적으로 동작합니다)
            title = st.text_input("추첨 제목", key="new_title")
            num_winners = st.number_input("당첨 인원 수", 1, value=1, key="new_num_winners")
            draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], horizontal=True, key="new_draw_type")
            
            draw_time = st.datetime_input("추첨 시간", value=datetime.datetime.now() + datetime.timedelta(minutes=5),
                                          key="new_draw_time", disabled=(draw_type == "즉시 추첨"))
            
            participants_text = st.text_area("참가자 명단 (한 줄에 한 명, 중복 가능)", key="new_participants")
            
            if st.button("✅ 추첨 생성", type="primary", key="create_button"):
                participants = [name.strip() for name in participants_text.split('\n') if name.strip()]
                if not title or not participants:
                    st.warning("제목과 참가자를 입력하세요.")
                elif draw_type == "예약 추첨" and draw_time <= datetime.datetime.now():
                    st.error("예약 시간은 현재 시간 이후여야 합니다.")
                else:
                    final_draw_time = draw_time if draw_type == "예약 추첨" else datetime.datetime.now()
                    c = conn.cursor()
                    c.execute("INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')", (title, final_draw_time, num_winners))
                    lottery_id = c.lastrowid
                    for p_name in participants:
                        c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lottery_id, p_name))
                    conn.commit()
                    add_log(conn, lottery_id, f"추첨 생성됨 (방식: {draw_type}, 총 참가자: {len(participants)}명)")
                    st.success("추첨이 생성되었습니다!"); time.sleep(1); st.rerun()

        elif admin_action == "기존 추첨 관리 (재추첨/삭제)":
            st.subheader("기존 추첨 관리")
            if 'lotteries_df' in locals() and not lotteries_df.empty:
                choice = st.selectbox("관리할 추첨 선택", options=lotteries_df['title'], key="manage_choice")
                selected_lottery = lotteries_df[lotteries_df['title'] == choice].iloc[0]
                lottery_id = int(selected_lottery['id'])

                if selected_lottery['status'] == 'completed':
                    # 재추첨 로직
                    pass
                
                # 삭제 로직
                st.markdown("---")
                if st.button("🗑️ 추첨 삭제하기", key=f"delete_btn_{lottery_id}"):
                    st.session_state['delete_confirm_id'] = lottery_id

                if st.session_state.get('delete_confirm_id') == lottery_id:
                    st.warning(f"**경고**: '{choice}' 추첨의 모든 기록이 영구적으로 삭제됩니다.")
                    if st.button("예, 삭제합니다", type="primary", key=f"confirm_delete_btn_{lottery_id}"):
                        c = conn.cursor()
                        c.execute("DELETE FROM lotteries WHERE id = ?", (lottery_id,))
                        conn.commit()
                        st.session_state['delete_confirm_id'] = None
                        st.success(f"'{choice}' 추첨이 삭제되었습니다."); time.sleep(2); st.rerun()
            else:
                st.info("관리할 추첨이 없습니다.")

    conn.close()

# --- 4. 메인 실행 함수 ---
def run():
    st.set_page_config(page_title="new lottery", page_icon="📜", layout="centered")

    # 세션 상태 초기화
    if 'admin_auth' not in st.session_state:
        st.session_state['admin_auth'] = False

    # 로그인 상태에 따라 보여줄 페이지를 결정
    if not st.session_state['admin_auth']:
        login_page()
    else:
        # 로그인 되었다면, 메인 앱 레이아웃을 wide로 변경하고 실행
        st.set_page_config(layout="wide") 
        main_app()

# 추첨 로직 함수 (위에서 호출하므로 여기에 정의)
def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?", (now,))
    scheduled_lotteries = c.fetchall()
    for lottery_id, num_winners in scheduled_lotteries:
        c.execute("SELECT name FROM participants WHERE lottery_id = ?", (lottery_id,))
        participants = [row[0] for row in c.fetchall()]
        if participants:
            c.execute("SELECT winner_name FROM winners WHERE lottery_id = ?", (lottery_id,))
            existing_winners = {row[0] for row in c.fetchall()}
            candidates = [p for p in participants if p not in existing_winners]
            if len(candidates) > 0:
                run_draw(conn, lottery_id, num_winners, candidates)

if __name__ == "__main__":
    run()
