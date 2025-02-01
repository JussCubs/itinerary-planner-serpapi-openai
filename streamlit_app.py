import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

# ------------------------------------------------------------------------------
# 1) CONFIG: Setup OpenAI + Secrets
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_KEY = st.secrets.get("SERPAPI_API_KEY", None)
SERPAPI_BASE_URL = "https://serpapi.com/search.json"

# ------------------------------------------------------------------------------
# 2) HIDDEN SEARCH: For Additional Ideas
# ------------------------------------------------------------------------------
def hidden_search_for_more_ideas(user_answers, trip_start, trip_end):
    """
    Use an AI prompt to generate custom search queries based on the user's 
    answers + travel dates. Then call SerpAPI once for each query. We'll 
    store and reuse these results unless the user changes their input.
    """
    # Step A: Ask AI for recommended search queries
    system_prompt = (
        "You are an advanced travel planner for Maui. "
        "The user has certain preferences and trip dates. "
        "Produce a brief JSON object with a 'search_queries' array of strings. "
        "These queries should reflect additional ideas or hidden gems. "
        "No disclaimers or extra text, just valid JSON with one key 'search_queries'."
    )
    user_context = (
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"Preferences:\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n"
        "Return only a JSON object like {\"search_queries\": [\"...\", \"...\"]}."
    )
    
    try:
        ai_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_context},
            ],
            temperature=0.7,
            max_tokens=600
        )
        raw = ai_response.choices[0].message.content.strip()
        data = json.loads(raw)
        queries = data.get("search_queries", [])
    except:
        # Fallback if AI query generation fails
        queries = [
            "Maui dining recommendations",
            "Must-see events in Maui",
            "Outdoor adventures on Maui",
        ]

    # Step B: Call SerpAPI for each query
    results = {}
    if SERPAPI_KEY:
        for q in queries:
            results[q] = fetch_serpapi_data(q)
    else:
        # If there's no SerpAPI key, just store an empty placeholder
        for q in queries:
            results[q] = {}

    return {
        "search_queries": queries,
        "search_results": results
    }

def fetch_serpapi_data(query, retries=3):
    """A helper to call SerpAPI behind the scenes."""
    params = {
        "engine": "google",
        "q": query,
        "location": "Maui, Hawaii",
        "api_key": SERPAPI_KEY,
        "hl": "en",
        "gl": "us"
    }
    for attempt in range(retries):
        try:
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        time.sleep(1)
    return {}

# ------------------------------------------------------------------------------
# 3) ITINERARY GENERATION (Always Fresh)
# ------------------------------------------------------------------------------
def generate_itinerary(user_answers, trip_start, trip_end, all_search_data):
    """
    Build a new day-by-day itinerary each time the user clicks the plan button,
    even if they haven't changed anything.
    
    We can optionally pass the existing search data to the AI, so it can incorporate 
    or reference it if needed. That’s up to you. 
    For simplicity, we'll just let it generate a plan based on the user's answers.
    """
    system_prompt = (
        "You create day-by-day Maui travel plans. Be warm, descriptive, but not too long. "
        "Here are the user's preferences and trip dates. Use your own knowledge. "
        "No disclaimers or mention of searching. Provide a single text-based itinerary."
    )

    # Summarize user answers
    user_input = (
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n"
        "Write a short, day-by-day plan in a friendly tone."
    )
    
    try:
        ai_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0.8,
            max_tokens=1600
        )
        return ai_response.choices[0].message.content.strip()
    except:
        return None

# ------------------------------------------------------------------------------
# 4) STREAMLIT APP
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Maui Itinerary Planner", layout="centered")

# Keep track of the dynamic questions
if "dynamic_questions" not in st.session_state:
    st.session_state.dynamic_questions = get_questions()

# We store user search data by input in a dictionary: 
#   { (answer1, answer2, answer3, start_date, end_date): { "search_queries": [...], "search_results": {...} } }
if "cached_search_data" not in st.session_state:
    st.session_state.cached_search_data = {}

# The itinerary text is always regenerated, but we keep it in session to display
if "itinerary_text" not in st.session_state:
    st.session_state.itinerary_text = None

# Start / End Dates
col1, col2 = st.columns(2)
with col1:
    start_date_val = st.date_input("When does your trip begin?", value=date.today(), key="start_date_mem")
with col2:
    end_date_val = st.date_input("When does your trip end?", value=date.today() + timedelta(days=5), key="end_date_mem")

st.markdown("# Plan Your Maui Adventure")

# Show the three dynamic questions
with st.form("maui_form"):
    ans1 = st.text_input(st.session_state.dynamic_questions[0], key="pref1")
    ans2 = st.text_input(st.session_state.dynamic_questions[1], key="pref2")
    ans3 = st.text_input(st.session_state.dynamic_questions[2], key="pref3")
    
    plan_btn = st.form_submit_button("Plan My Maui Adventure")

    if plan_btn:
        if start_date_val > end_date_val:
            st.error("Please ensure your start date is before your end date.")
        else:
            user_answers = (ans1.strip(), ans2.strip(), ans3.strip())
            input_key = user_answers + (str(start_date_val), str(end_date_val))

            # 1) Check if we already have search data for these inputs
            if input_key not in st.session_state.cached_search_data:
                # We'll fetch new search data just once for these inputs
                st.info("Gathering ideas for your trip...")
                new_data = hidden_search_for_more_ideas(user_answers, start_date_val, end_date_val)
                st.session_state.cached_search_data[input_key] = new_data

            # 2) Regardless of new or old search data, we always generate a fresh itinerary
            st.info("Creating your custom itinerary...")
            search_data_for_ai = st.session_state.cached_search_data[input_key]
            new_itinerary = generate_itinerary(user_answers, start_date_val, end_date_val, search_data_for_ai)
            if new_itinerary is None:
                st.error("Something went wrong while building your itinerary. Please try again.")
            else:
                st.session_state.itinerary_text = new_itinerary
                st.success("Your Maui plan is ready! Scroll down to check it out.")

# ------------------------------------------------------------------------------
# DISPLAY ITINERARY
# ------------------------------------------------------------------------------
if st.session_state.itinerary_text:
    st.markdown("---")
    st.markdown("## Your Day-by-Day Maui Itinerary")
    st.markdown(st.session_state.itinerary_text)

    # Share / Download
    itinerary_txt = st.session_state.itinerary_text
    st.download_button(
        label="Share This Itinerary",
        data=itinerary_txt,
        file_name="my_maui_itinerary.txt",
        mime="text/plain"
    )
    email_subject = quote_plus("My Maui Trip Plan!")
    email_body = quote_plus(itinerary_txt)
    mailto_link = f"mailto:?subject={email_subject}&body={email_body}"
    st.markdown(f"[Email This Itinerary]({mailto_link})")

    # ----------------------------------------------------------------------------
    # EXTRA IDEAS (same data if user hasn't changed anything)
    # ----------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("## More Ideas to Explore")
    input_key = (st.session_state.pref1.strip(), 
                 st.session_state.pref2.strip(),
                 st.session_state.pref3.strip(),
                 str(st.session_state.start_date_mem),
                 str(st.session_state.end_date_mem))
    if input_key not in st.session_state.cached_search_data:
        st.write("No extra ideas found yet. Please plan your trip first.")
    else:
        search_info = st.session_state.cached_search_data[input_key]
        queries = search_info.get("search_queries", [])
        results_dict = search_info.get("search_results", {})
        
        if not queries:
            st.write("We couldn't find more ideas at this time.")
        else:
            for q in queries:
                st.markdown(f"### {q}")
                data = results_dict.get(q, {})
                if "organic_results" not in data:
                    st.write("*(No extra suggestions found right now.)*")
                    st.markdown("---")
                    continue
                # show top 2 or 3
                top_items = data["organic_results"][:3]
                for item in top_items:
                    title = item.get("title", "Untitled")
                    link = item.get("link", "#")
                    snippet = item.get("snippet", "")
                    st.markdown(f"**{title}**")
                    st.write(snippet)
                    st.markdown(f"[Learn more]({link})")
                st.markdown("---")
