import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

# ------------------------------------------------------------------------------
# 1) STREAMLIT CONFIG: Must be the first command
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Maui Itinerary Planner (RAG + Hotel)", layout="centered")

# ------------------------------------------------------------------------------
# 2) OPENAI & SERPAPI SETUP
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_KEY = st.secrets.get("SERPAPI_API_KEY", None)
SERPAPI_BASE_URL = "https://serpapi.com/search.json"

# ------------------------------------------------------------------------------
# 3) HELPER FUNCTIONS
# ------------------------------------------------------------------------------

def get_questions():
    """
    Generate 3 user-friendly questions about the trip from gpt-4o.
    We'll add a 4th question (hotel) ourselves for consistency.
    """
    system_prompt = "You are a friendly travel assistant helping plan a trip."
    user_prompt = (
        "Provide three short, thoughtful questions about a traveler's preferences. "
        "Return them as a JSON list of exactly three strings, no extra text."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Using 'gpt-4o' as requested
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
            raise ValueError("Expected exactly 3 questions in a JSON list.")
        # Insert a 4th question about the hotel
        q_list.append("Which hotel are you staying at?")
        return q_list
    except:
        return [
            "What excites you most about traveling there?",
            "What sort of dining do you enjoy?",
            "Do you have any must-do activities (like hiking or snorkeling)?",
            "Which hotel are you staying at?",
        ]

def hidden_search_for_more_ideas(user_answers, trip_start, trip_end, location):
    """
    1) Asks GPT for custom search queries based on user answers, dates, and location.
    2) For each query, calls SerpAPI and caches the results.
    """
    # user_answers includes the hotel name at index 3 now
    system_prompt = (
        "You are an advanced travel planner. "
        "The user has certain preferences, travel dates, and a location. "
        "Produce a short JSON: { \"search_queries\": [ ... ] } with relevant queries, no disclaimers or extra text."
    )
    user_context = (
        f"Location: {location}\n"
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"Preferences:\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n"
        f"Hotel: {user_answers[3]}\n"
        "Return only {\"search_queries\": [\"...\"]}."
    )

    # Ask GPT for the search queries
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
        # Fallback if GPT fails
        queries = [
            f"Dining in {location}",
            f"Must-see events in {location}",
            f"Fun outdoor activities in {location}"
        ]

    # For each query, call SerpAPI
    results = {}
    if SERPAPI_KEY:
        for q in queries:
            results[q] = fetch_serpapi_data(q, location)
    else:
        for q in queries:
            results[q] = {}

    return {
        "search_queries": queries,
        "search_results": results
    }

def fetch_serpapi_data(query, location, retries=3):
    """
    Query SerpAPI for top Google results:
    - 'organic_results' (title, link, snippet)
    - 'local_results' / 'places' (title, rating, reviews, address, possibly a link)
    No phone numbers per request.
    """
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
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        time.sleep(2)
    return {}

def gather_rag_data(all_search_data):
    """
    Gather relevant data from SerpAPI results, including rating, snippet, address, link, etc.
    We pass this to GPT as bullet points for 'RAG' usage. 
    - We ensure each place has a 'title' and a 'link' if possible, 
      so GPT can embed it in the final itinerary as requested.
    """
    queries = all_search_data.get("search_queries", [])
    results_dict = all_search_data.get("search_results", {})

    if not queries:
        return "(No extra data found.)"

    lines = []
    for q in queries:
        data = results_dict.get(q, {})
        # 1) Possibly get 'organic_results'
        if "organic_results" in data:
            org_items = data["organic_results"][:3]  # up to 3
            for item in org_items:
                title = item.get("title", "Untitled")
                link = item.get("link", "")
                snippet = item.get("snippet", "")
                # We'll store them in a bullet with a link
                line = (
                    f"- Title: {title}\n"
                    f"  Link: {link}\n"
                    f"  Snippet: {snippet[:120]}..."
                )
                lines.append(line)

        # 2) Possibly get 'local_results' or 'local_map' data
        if "local_results" in data:
            local_items = data["local_results"].get("places", [])[:3]
            for item in local_items:
                title = item.get("title", "Untitled")
                rating = item.get("rating", "No rating")
                reviews = item.get("reviews", "No reviews info")
                address = item.get("address", "No address")
                # SerpAPI local results may have 'website' or 'link'
                link = item.get("website", item.get("link", ""))
                line = (
                    f"- Local: {title}\n"
                    f"  Link: {link}\n"
                    f"  Rating: {rating}, Reviews: {reviews}\n"
                    f"  Address: {address}"
                )
                lines.append(line)

    if not lines:
        return "(No extra data found.)"
    return "\n".join(lines)

def generate_itinerary(user_answers, trip_start, trip_end, location, all_search_data):
    """
    Build a short day-by-day itinerary referencing the SERP data for RAG usage.
    We explicitly tell GPT to embed a link for EVERY place it uses from the snippet.
    """
    rag_snippet = gather_rag_data(all_search_data)

    system_prompt = (
        "You create a concise, day-by-day travel plan in Markdown, referencing real data from the user. "
        "The user has specified a hotel name. For EVERY place you mention from the snippet, "
        "you MUST include the link in your Markdown text. Keep it short, friendly, minimal disclaimers, "
        "and well-formatted. Avoid any code references."
    )

    user_input = f"""Location: {location}
Trip Dates: {trip_start} to {trip_end}
Preferences:
1) {user_answers[0]}
2) {user_answers[1]}
3) {user_answers[2]}
Hotel: {user_answers[3]}

Here is extra data from search results (RAG). Each item has a title, link, snippet, rating, etc.:

{rag_snippet}

Please create a short day-by-day plan. If you mention any place/event from the snippet, 
MUST include its link in Markdown (e.g., [Place Title](link)). 
"""

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
# 4a) Session state
if "dynamic_questions" not in st.session_state:
    st.session_state.dynamic_questions = get_questions()

if "cached_search_data" not in st.session_state:
    st.session_state.cached_search_data = {}

if "itinerary_text" not in st.session_state:
    st.session_state.itinerary_text = None

# 4b) UI
st.markdown("# Plan Your Maui Adventure (RAG + Hotel)")
st.markdown("Short itinerary referencing your hotel and real local spots, with **required** links in the final plan.")

location_val = st.text_input("Where are you going?", value="Maui, Hawaii")

col1, col2 = st.columns(2)
with col1:
    start_date_val = st.date_input("When does your trip begin?", value=date.today())
with col2:
    end_date_val = st.date_input("When does your trip end?", value=date.today() + timedelta(days=5))

st.subheader("Your Preferences")
with st.form("trip_form"):
    # We now have 4 questions, the last one is about the hotel
    q1 = st.session_state.dynamic_questions[0]
    q2 = st.session_state.dynamic_questions[1]
    q3 = st.session_state.dynamic_questions[2]
    q4 = st.session_state.dynamic_questions[3]  # "Which hotel are you staying at?"

    user_answer1 = st.text_input(q1, key="ans1")
    user_answer2 = st.text_input(q2, key="ans2")
    user_answer3 = st.text_input(q3, key="ans3")
    user_answer4 = st.text_input(q4, key="ans4")

    plan_btn = st.form_submit_button("Plan My Adventure")

    if plan_btn:
        if start_date_val > end_date_val:
            st.error("Please ensure your start date is before your end date.")
        else:
            user_ans_tuple = (
                user_answer1.strip(),
                user_answer2.strip(),
                user_answer3.strip(),
                user_answer4.strip(),
                str(start_date_val),
                str(end_date_val),
                location_val.strip(),
            )

            # Fetch or reuse the search data
            if user_ans_tuple not in st.session_state.cached_search_data:
                st.info("Gathering extra data for your trip (RAG style)...")
                new_data = hidden_search_for_more_ideas(
                    (user_answer1.strip(), user_answer2.strip(), user_answer3.strip(), user_answer4.strip()),
                    start_date_val,
                    end_date_val,
                    location_val.strip()
                )
                st.session_state.cached_search_data[user_ans_tuple] = new_data

            st.info("Creating your itinerary with mandatory links for every recommended spot...")
            search_data_for_ai = st.session_state.cached_search_data[user_ans_tuple]
            new_itinerary = generate_itinerary(
                (user_answer1.strip(), user_answer2.strip(), user_answer3.strip(), user_answer4.strip()),
                start_date_val,
                end_date_val,
                location_val.strip(),
                search_data_for_ai
            )
            if new_itinerary is None:
                st.error("Something went wrong. Please try again.")
            else:
                st.session_state.itinerary_text = new_itinerary
                st.success("Your itinerary is ready! Scroll down to see it.")

# ------------------------------------------------------------------------------
# 5) DISPLAY ITINERARY
# ------------------------------------------------------------------------------
if st.session_state.itinerary_text:
    st.markdown("---")
    st.markdown("## Your Day-by-Day Plan")
    st.markdown(st.session_state.itinerary_text)  # GPT's final output in Markdown

    # Let user share / download
    itinerary_txt = st.session_state.itinerary_text
    st.download_button(
        label="Share This Itinerary",
        data=itinerary_txt,
        file_name="my_maui_rag_itinerary.txt",
        mime="text/plain"
    )
    email_subject = quote_plus("Check out my Maui trip plan!")
    email_body = quote_plus(itinerary_txt)
    mailto_link = f"mailto:?subject={email_subject}&body={email_body}"
    st.markdown(f"[Email This Itinerary]({mailto_link})")

    st.markdown("---")
    st.markdown("## More Ideas from the Web")
    user_ans_tuple = (
        st.session_state.ans1.strip(),
        st.session_state.ans2.strip(),
        st.session_state.ans3.strip(),
        st.session_state.ans4.strip(),
        str(start_date_val),
        str(end_date_val),
        location_val.strip(),
    )
    if user_ans_tuple not in st.session_state.cached_search_data:
        st.write("No extra data found. Please plan your trip first.")
    else:
        # Show the queries & top results with direct links
        search_info = st.session_state.cached_search_data[user_ans_tuple]
        queries = search_info.get("search_queries", [])
        results_dict = search_info.get("search_results", {})

        if not queries:
            st.write("We didn't find more ideas at this time.")
        else:
            for q in queries:
                st.markdown(f"### {q}")
                data = results_dict.get(q, {})
                # Show top 2 or 3 results from organic_results
                if "organic_results" in data:
                    top_items = data["organic_results"][:3]
                    for item in top_items:
                        title = item.get("title", "Untitled")
                        link = item.get("link", "#")
                        snippet = item.get("snippet", "")
                        st.markdown(f"**{title}**")
                        st.write(snippet)
                        st.markdown(f"[Visit Site]({link})")

                # If there's local results (no phone numbers)
                if "local_results" in data:
                    places = data["local_results"].get("places", [])[:3]
                    for place in places:
                        title = place.get("title", "Untitled")
                        rating = place.get("rating", "No rating")
                        reviews = place.get("reviews", "No reviews info")
                        address = place.get("address", "No address")
                        # Some local_results might have "website" or "link"
                        place_link = place.get("website", place.get("link", "#"))

                        st.markdown(f"**{title}**")
                        st.write(f"Rating: {rating}, Reviews: {reviews}")
                        st.write(f"Address: {address}")
                        if place_link and place_link != "#":
                            st.markdown(f"[Visit Site]({place_link})")
                st.markdown("---")
