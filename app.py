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
    # detect_types를 추가하여 timestamp를 datetime 객체로 자동 변환
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False,
                           detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
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
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message, log_timestamp) VALUES (?, ?, ?)",
              (lottery_id, message, now_kst()))
    conn.commit()

def run_draw(conn, lottery_id, num_to_draw, candidates):
    actual = min(num_to_draw, len(candidates))
    if actual <= 0: return []
    winners = random.sample(candidates, k=actual)
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    prev_round = c.fetchone()[0] or 0
    current_round = prev_round + 1
    for w in winners:
        c.execute("INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)", (lottery_id, w, current_round))
    c.execute("UPDATE lotteries SET status='completed' WHERE id=?", (lottery_id,))
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 진행. 당첨자: {', '.join(winners)}")
    return winners

def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    c.execute("SELECT id, num_winners, title FROM lotteries WHERE status='scheduled' AND draw_time <= ?", (now_kst(),))
    for lid, num, title in c.fetchall():
        all_participants = [r[0] for r in c.execute("SELECT name FROM participants WHERE lottery_id=?", (lid,))]
        if all_participants:
            # 이미 당첨된 사람을 제외하고 추첨을 진행해야 함
            prev_winners = {r[0] for r in c.execute("SELECT winner_name FROM winners WHERE lottery_id=?", (lid,))}
            candidates = [p for p in all_participants if p not in prev_winners]
            if candidates:
                winners = run_draw(conn, lid, num, candidates)
                if winners:
                    st.session_state[f'celebrated_{lid}'] = True

# --- Streamlit UI (최종 개선 버전) ---
def main():
    st.set_page_config(page_title="NEW LOTTERY", page_icon="📜", layout="wide")
    st_autorefresh(interval=1000, limit=None, key="refresher") # 1초로 변경
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    st.session_state.setdefault('admin_auth', False)
    st.session_state.setdefault('delete_confirm_id', None)

    st.title("📜 모두가 함께 보는 실시간 추첨")
    col1, col2 = st.columns([2, 1])

    # 좌측: 추첨 목록 및 상세 정보
    with col1:
        st.header("🎟️ 추첨 목록 및 상세 정보")
        lotteries_df = pd.read_sql("SELECT id, title, draw_time, status FROM lotteries ORDER BY id DESC", conn,
                                   parse_dates=['draw_time'])
        
        if lotteries_df.empty:
            st.info("생성된 추첨이 없습니다. 관리자 메뉴에서 추첨을 만들어주세요.")
        else:
            # 목록 생성을 위한 데이터 준비
            options_map = {}
            for index, row in lotteries_df.iterrows():
                status_emoji = "🟢 진행중" if row['status'] == 'scheduled' else "🏁 완료"
                option_label = f"{row['title']} | {status_emoji}"
                options_map[option_label] = int(row['id'])

            # 라디오 버튼을 사용해 클릭 가능한 목록 구현
            selected_option = st.radio(
                "확인할 추첨을 선택하세요:",
                options=options_map.keys(),
                key="lottery_selector",
                label_visibility="collapsed" # 라벨("확인할...")은 숨김
            )
            
            # 선택된 추첨의 상세 정보 표시
            if selected_option:
                selected_id = options_map[selected_option]
                sel = lotteries_df[lotteries_df['id'] == selected_id].iloc[0]
                lid, title, status, draw_time = int(sel['id']), sel['title'], sel['status'], sel['draw_time']
                
                if draw_time.tzinfo is None:
                    draw_time = draw_time.tz_localize(KST)

                with st.container(border=True):
                    st.subheader(f"✨ {title}")
                    if status == 'completed':
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')})")
                        winners_df = pd.read_sql("SELECT winner_name, draw_round FROM winners WHERE lottery_id=? ORDER BY draw_round", conn, params=(lid,))
                        for round_num, group in winners_df.groupby('draw_round'):
                            round_text = f"{round_num}회차" if round_num == 1 else f"{round_num}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {round_text} 당첨자")
                            winner_tags = " &nbsp; ".join([f"<span style='background-color:#E8F5E9; color:#1E8E3E; border-radius:5px; padding:5px 10px; font-weight:bold;'>{name}</span>" for name in group['winner_name']])
                            st.markdown(f"<p style='text-align:center; font-size: 20px;'>{winner_tags}</p>", unsafe_allow_html=True)
                        if st.session_state.get(f'celebrated_{lid}', False):
                            st.balloons(); st.session_state[f'celebrated_{lid}'] = False
                    else: # scheduled
                        diff = draw_time - now_kst()
                        if diff.total_seconds() > 0:
                            st.info(f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')} (남은 시간: {str(diff).split('.')[0]})")
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 자동으로 진행됩니다...")

                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        participants_df = pd.read_sql("SELECT name FROM participants WHERE lottery_id=?", conn, params=(lid,))
                        st.dataframe(participants_df.rename(columns={'name': '이름'}), use_container_width=True, height=200)
                    with tab2:
                        logs_df = pd.read_sql("SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp) as 시간, log_message as 내용 FROM lottery_logs WHERE lottery_id=? ORDER BY id", conn, params=(lid,))
                        st.dataframe(logs_df, use_container_width=True, height=200)

    # 우측: 관리자 메뉴
    with col2:
        st.header("👑 관리자 메뉴")
        if not st.session_state['admin_auth']:
            pw = st.text_input("관리자 코드", type="password", key="admin_pw")
            if st.button("인증"):
                try:
                    if pw == st.secrets["admin"]["password"]:
                        st.session_state['admin_auth'] = True
                        st.experimental_rerun()
                except KeyError:
                    st.error("Secrets에 [admin] password가 설정되지 않았습니다.")
        else:
            st.success("관리자 모드 활성화")
            action = st.radio("작업 선택", ["새 추첨 만들기", "기존 추첨 관리"], key="admin_action_radio", horizontal=True)

            if action == "새 추첨 만들기":
                with st.form("new_lottery_form"):
                    st.subheader("새 추첨 만들기")
                    title = st.text_input("추첨 제목")
                    num_winners = st.number_input("당첨 인원 수", min_value=1, value=1)
                    draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], key="new_draw_type", horizontal=True)

                    # 예약 시간 선택 오류 해결: st.datetime_input 사용
                    draw_time_to_set = st.datetime_input(
                        "예약 시간 (KST)",
                        value=now_kst() + datetime.timedelta(minutes=5),
                        step=datetime.timedelta(minutes=1),
                        key="new_draw_datetime",
                        disabled=(draw_type == "즉시 추첨")
                    )
                    
                    participants_txt = st.text_area("참가자 명단 (한 줄에 한 명씩, 중복 가능)", height=150)
                    submitted = st.form_submit_button("✅ 추첨 생성", type="primary")

                    if submitted:
                        names = [n.strip() for n in participants_txt.split('\n') if n.strip()]
                        final_draw_time = now_kst() if draw_type == "즉시 추첨" else draw_time_to_set.astimezone(KST)
                        if not title or not names:
                            st.warning("제목과 최소 한 명 이상의 참가자를 입력하세요.")
                        elif draw_type == "예약 추첨" and final_draw_time <= now_kst():
                            st.error("예약 추첨 시간은 현재 시간 이후여야 합니다.")
                        else:
                            c = conn.cursor()
                            c.execute("INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')",
                                      (title, final_draw_time, num_winners))
                            lid = c.lastrowid
                            for n in names:
                                c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lid, n))
                            conn.commit()
                            add_log(conn, lid, f"추첨 생성 (방식: {draw_type}, 참가자 수: {len(names)})")
                            st.success("추첨이 성공적으로 생성되었습니다.")
                            time.sleep(1); st.experimental_rerun()
            else: # 기존 추첨 관리
                st.subheader("기존 추첨 관리")
                if not lotteries_df.empty:
                    choice = st.selectbox("관리할 추첨 선택", lotteries_df['title'], key="manage_choice")
                    sel = lotteries_df[lotteries_df['title'] == choice].iloc[0]
                    lid = int(sel['id'])

                    if sel['status'] == 'completed':
                        # ... 재추첨 로직 ...
                        pass
                    
                    st.markdown("---")
                    st.write("**추첨 삭제**")
                    if st.button("🗑️ 이 추첨 삭제하기", key=f"delete_btn_{lid}"):
                        st.session_state['delete_confirm_id'] = lid
                    
                    if st.session_state.get('delete_confirm_id') == lid:
                        st.warning(f"**경고**: '{sel['title']}' 추첨의 모든 기록이 영구적으로 삭제됩니다.")
                        if st.button("예, 정말로 삭제합니다", key=f"confirm_del_btn_{lid}", type="primary"):
                            c = conn.cursor()
                            c.execute("DELETE FROM lotteries WHERE id=?", (lid,)); conn.commit()
                            st.session_state['delete_confirm_id'] = None
                            st.success("추첨이 삭제되었습니다."); time.sleep(1); st.experimental_rerun()
                else:
                    st.info("관리할 추첨이 없습니다.")
    conn.close()

if __name__ == '__main__':
    main()
