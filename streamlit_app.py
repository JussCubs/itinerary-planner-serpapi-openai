import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

# 1) MUST BE THE FIRST STREAMLIT COMMAND:
st.set_page_config(page_title="Maui Itinerary Planner", layout="centered")

# 2) OPENAI & SERPAPI SETUP
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_KEY = st.secrets.get("SERPAPI_API_KEY", None)
SERPAPI_BASE_URL = "https://serpapi.com/search.json"

# ------------------------------------------------------------------------------
# 3) HELPER FUNCTIONS
# ------------------------------------------------------------------------------
def get_questions():
    """
    Generate 3 user-friendly questions about the trip.
    """
    system_prompt = "You are a friendly travel assistant helping someone plan a trip."
    user_prompt = (
        "Provide three short, thoughtful questions to learn about someone's trip preferences. "
        "Respond with a JSON array of exactly three strings, no extra text."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        q_list = json.loads(content)
        if not isinstance(q_list, list) or len(q_list) != 3:
            raise ValueError("Expected 3 questions in a JSON list.")
        return q_list
    except:
        # Fallback if anything goes wrong
        return [
            "What excites you most about your destination?",
            "What kind of dining experiences do you enjoy?",
            "Which activities (like hiking or snorkeling) would you love to do?"
        ]


def hidden_search_for_more_ideas(user_answers, trip_start, trip_end, location):
    """
    Use an AI prompt to generate custom search queries based on the user's
    answers + travel dates + location. Then call SerpAPI once for each query.
    """
    # Step A: Ask AI for recommended search queries
    system_prompt = (
        "You are an advanced travel planner. The user has certain preferences, travel dates, and a location. "
        "Produce a short JSON object: { \"search_queries\": [ ... ] } with any relevant queries. "
        "No disclaimers or extra text."
    )
    user_context = (
        f"Location: {location}\n"
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"Preferences:\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n"
        "Return only a JSON object like {\"search_queries\": [\"...\", \"...\"]}."
    )

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o",
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
            f"{location} dining recommendations",
            f"Must-see events in {location}",
            f"Outdoor adventures in {location}",
        ]

    # Step B: Call SerpAPI for each query
    results = {}
    if SERPAPI_KEY:
        for q in queries:
            results[q] = fetch_serpapi_data(q, location)
    else:
        # If there's no SerpAPI key, just store an empty placeholder
        for q in queries:
            results[q] = {}

    return {
        "search_queries": queries,
        "search_results": results
    }


def fetch_serpapi_data(query, location, retries=3):
    """A helper to call SerpAPI behind the scenes, using user-specified location."""
    if not SERPAPI_KEY:
        return {}
    params = {
        "engine": "google",
        "q": query,
        "location": location,
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


def generate_itinerary(user_answers, trip_start, trip_end, location, all_search_data):
    """
    Always regenerate a day-by-day itinerary each time user clicks the plan button.
    """
    system_prompt = (
        "You create a day-by-day travel plan. Be warm, descriptive, and user-friendly. "
        "No disclaimers or code references, just text. "
        "You know the user's location, preferences, and trip dates."
    )
    # Summarize user answers
    user_input = (
        f"Location: {location}\n"
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n"
        "Write a short, day-by-day plan in a friendly tone."
    )

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o",
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
# Keep track of the dynamic questions
if "dynamic_questions" not in st.session_state:
    st.session_state.dynamic_questions = get_questions()

# We'll store user search data by input in a dictionary:
# { (answer1, answer2, answer3, start_date, end_date, location): { "search_queries": [...], "search_results": {...} } }
if "cached_search_data" not in st.session_state:
    st.session_state.cached_search_data = {}

# The itinerary text is always regenerated, but we keep it in session to display
if "itinerary_text" not in st.session_state:
    st.session_state.itinerary_text = None

# ---------------------------------------------
# UI: Title, location input, date inputs, etc.
# ---------------------------------------------
st.markdown("# Plan Your Next Adventure")
st.markdown("Create a custom itinerary—no tech jargon, just a smooth trip planning experience.")

location_val = st.text_input("Where are you going?", value="Maui, Hawaii")

col1, col2 = st.columns(2)
with col1:
    start_date_val = st.date_input("When does your trip begin?", value=date.today(), key="start_date_mem")
with col2:
    end_date_val = st.date_input("When does your trip end?", value=date.today() + timedelta(days=5), key="end_date_mem")

st.subheader("Your Preferences")
with st.form("trip_form"):
    user_answer1 = st.text_input(st.session_state.dynamic_questions[0], key="ans1")
    user_answer2 = st.text_input(st.session_state.dynamic_questions[1], key="ans2")
    user_answer3 = st.text_input(st.session_state.dynamic_questions[2], key="ans3")

    plan_btn = st.form_submit_button("Plan My Adventure")

    if plan_btn:
        if start_date_val > end_date_val:
            st.error("Please ensure your start date is before your end date.")
        else:
            user_ans_tuple = (
                user_answer1.strip(),
                user_answer2.strip(),
                user_answer3.strip(),
                str(start_date_val),
                str(end_date_val),
                location_val.strip(),
            )
            # 1) If we haven't fetched search data for these inputs, do it now
            if user_ans_tuple not in st.session_state.cached_search_data:
                st.info("Gathering extra ideas for your trip...")
                new_data = hidden_search_for_more_ideas(
                    (user_answer1.strip(), user_answer2.strip(), user_answer3.strip()),
                    start_date_val,
                    end_date_val,
                    location_val.strip()
                )
                st.session_state.cached_search_data[user_ans_tuple] = new_data

            # 2) Always generate a fresh itinerary
            st.info("Putting together your custom itinerary...")
            search_data_for_ai = st.session_state.cached_search_data[user_ans_tuple]
            new_itinerary = generate_itinerary(
                (user_answer1.strip(), user_answer2.strip(), user_answer3.strip()),
                start_date_val,
                end_date_val,
                location_val.strip(),
                search_data_for_ai
            )
            if new_itinerary is None:
                st.error("Something went wrong. Please try again.")
            else:
                st.session_state.itinerary_text = new_itinerary
                st.success("Your itinerary is ready! Scroll down to check it out.")


# ------------------------------------------------------------------------------
# 5) DISPLAY ITINERARY
# ------------------------------------------------------------------------------
if st.session_state.itinerary_text:
    st.markdown("---")
    st.markdown("## Your Day-by-Day Plan")
    st.markdown(st.session_state.itinerary_text)

    # Share / Download
    itinerary_txt = st.session_state.itinerary_text
    st.download_button(
        label="Share This Itinerary",
        data=itinerary_txt,
        file_name="my_trip_itinerary.txt",
        mime="text/plain"
    )
    email_subject = quote_plus("Check out my trip plan!")
    email_body = quote_plus(itinerary_txt)
    mailto_link = f"mailto:?subject={email_subject}&body={email_body}"
    st.markdown(f"[Email This Itinerary]({mailto_link})")

    # Extra Ideas
    st.markdown("---")
    st.markdown("## More Ideas to Explore")
    user_ans_tuple = (
        st.session_state.ans1.strip(),
        st.session_state.ans2.strip(),
        st.session_state.ans3.strip(),
        str(st.session_state.start_date_mem),
        str(st.session_state.end_date_mem),
        location_val.strip(),
    )
    if user_ans_tuple not in st.session_state.cached_search_data:
        st.write("No extra ideas found yet. Please plan your trip first.")
    else:
        search_info = st.session_state.cached_search_data[user_ans_tuple]
        queries = search_info.get("search_queries", [])
        results_dict = search_info.get("search_results", {})

        if not queries:
            st.write("We couldn't find more ideas at this time.")
        else:
            for q in queries:
                st.markdown(f"### {q}")
                data = results_dict.get(q, {})
                if "organic_results" not in data:
                    st.write("*(No extra suggestions found.)*")
                    st.markdown("---")
                    continue
                # Show top 2 or 3 results
                top_items = data["organic_results"][:3]
                for item in top_items:
                    title = item.get("title", "Untitled")
                    link = item.get("link", "#")
                    snippet = item.get("snippet", "")
                    st.markdown(f"**{title}**")
                    st.write(snippet)
                    st.markdown(f"[Learn more]({link})")
                st.markdown("---")
