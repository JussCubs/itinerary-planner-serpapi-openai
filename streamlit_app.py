import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

# ------------------------------------------------------------------------------
# SETUP: OpenAI & "Hidden" Additional Searches
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# We'll do some hidden searches to gather extra suggestions behind the scenes,
# but won't mention the word "SerpAPI" or "JSON" to the user. We'll just say,
# "we found additional ideas for you."
EXTRA_SEARCH_CATEGORIES = {
    "Dining": "Maui dining options",
    "Events": "What's happening in Maui",
    "Outdoor Fun": "Outdoor adventures in Maui",
    "Local Culture": "Maui cultural highlights",
    "Hidden Gems": "Unique off-the-beaten-path attractions in Maui",
}

# Helper to get "hidden" search results
def hidden_search_for_more_ideas(query, retries=3):
    """We'll make a hidden call to SerpAPI (or any search API) to fetch extra ideas."""
    base_url = "https://serpapi.com/search.json"
    api_key = st.secrets.get("SERPAPI_API_KEY", None)

    # If we don't have a SerpAPI key, just return an empty dict
    if not api_key:
        return {}

    params = {
        "engine": "google",
        "q": query,
        "location": "Maui, Hawaii",
        "api_key": api_key,
        "hl": "en",
        "gl": "us"
    }

    for attempt in range(retries):
        try:
            resp = requests.get(base_url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        time.sleep(1)
    return {}

# ------------------------------------------------------------------------------
# QUESTION GENERATION
# ------------------------------------------------------------------------------
def get_questions():
    """
    Generate three friendly, no-jargon questions about the trip.
    Returns a list of 3 question strings.
    """
    prompt = (
        "You are a helpful, friendly travel planner for Maui. "
        "Please provide three short questions in plain language to help plan a Maui trip. "
        "Use a simple list format. Example: ['Q1', 'Q2', 'Q3']"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a friendly travel planner."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=200,
        )
        txt = response.choices[0].message.content.strip()
        qlist = json.loads(txt)
        if not isinstance(qlist, list) or len(qlist) != 3:
            raise ValueError("Expected 3 items in list.")
        return qlist
    except:
        # Fallback if the call fails or parse fails
        return [
            "What excites you most about visiting Maui?",
            "What types of cuisine or dining experiences do you enjoy?",
            "Are there any special activities, like hiking or snorkeling, you'd love to do?"
        ]

# ------------------------------------------------------------------------------
# ITINERARY GENERATION (with caching by user input)
# ------------------------------------------------------------------------------
def generate_itinerary(answers, start_date, end_date):
    """
    Build a day-by-day plan. We'll talk to GPT behind the scenes.
    We'll keep it simple for the user, no mention of "JSON" or "queries."
    """
    # Create a simple user-friendly prompt for GPT
    system_prompt = (
        "You create day-by-day travel plans for Maui. "
        "Include fun activities, sights, dining suggestions, and local culture. "
        "Be warm and descriptive, but not too long. "
        "User wants a daily plan from Start Date to End Date. "
        "No extra disclaimers or code-like formats."
    )

    # Build a summary of what the user said
    user_pref_summary = (
        f"Trip Dates: {start_date} to {end_date}.\n"
        f"Preferences:\n"
        f"1) {answers[0]}\n"
        f"2) {answers[1]}\n"
        f"3) {answers[2]}\n"
        "\nProvide a day-by-day plan. Write it in a friendly tone."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_pref_summary},
            ],
            temperature=0.8,
            max_tokens=1800,
        )
        itinerary_text = response.choices[0].message.content.strip()
        return itinerary_text
    except Exception as e:
        return None

# ------------------------------------------------------------------------------
# STREAMLIT APP
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Maui Itinerary Planner", layout="centered")

# Cache user Q&A to handle repeated requests
if "generated_questions" not in st.session_state:
    st.session_state.generated_questions = get_questions()

if "cached_itineraries" not in st.session_state:
    # We'll store itineraries in a dictionary with a key based on user inputs
    st.session_state.cached_itineraries = {}

st.markdown("# Maui Itinerary Planner")
st.markdown("Enjoy a customized, day-by-day plan for your dream trip to Maui!\n")

# Date selection
col_left, col_right = st.columns(2)
with col_left:
    start_date = st.date_input("When does your trip begin?", value=date.today())
with col_right:
    end_date = st.date_input("When does your trip end?", value=date.today() + timedelta(days=5))

if start_date > end_date:
    st.error("Your start date cannot be after your end date!")
    st.stop()

# Show the three questions
st.subheader("Tell Us About Your Preferences")
with st.form(key="trip_form"):
    ans1 = st.text_input(st.session_state.generated_questions[0], key="a1")
    ans2 = st.text_input(st.session_state.generated_questions[1], key="a2")
    ans3 = st.text_input(st.session_state.generated_questions[2], key="a3")

    submit_btn = st.form_submit_button("Plan My Maui Adventure")

# If the user clicked "Plan My Maui Adventure"...
if submit_btn:
    user_answers = [ans1.strip(), ans2.strip(), ans3.strip()]
    # Build a cache key from answers + dates
    cache_key = (user_answers[0], user_answers[1], user_answers[2], str(start_date), str(end_date))

    # Check if we have a cached itinerary for these exact inputs
    if cache_key in st.session_state.cached_itineraries:
        st.success("Using your previously generated itinerary!")
        st.session_state.current_itinerary = st.session_state.cached_itineraries[cache_key]
    else:
        # Otherwise, generate a new itinerary
        st.info("Planning your trip...")
        itinerary_result = generate_itinerary(user_answers, start_date, end_date)
        if itinerary_result is None:
            st.error("Something went wrong while planning your trip. Please try again later.")
            st.stop()
        # Store in cache
        st.session_state.cached_itineraries[cache_key] = itinerary_result
        st.session_state.current_itinerary = itinerary_result
        st.success("Your trip plan is ready! Scroll down to see details.")

# If we have a "current_itinerary" in session state, show it
if "current_itinerary" in st.session_state:
    st.markdown("---")
    st.markdown("## Your Maui Travel Plan")
    final_plan = st.session_state.current_itinerary
    st.markdown(final_plan)

    # Provide a share/download feature
    # Download button for the text itinerary
    st.download_button(
        label="Share This Itinerary",
        data=final_plan,
        file_name="my_maui_itinerary.txt",
        mime="text/plain"
    )
    
    # Simple email link
    email_subject = quote_plus("Check out my Maui Trip Plan!")
    email_body = quote_plus(final_plan)
    mailto_link = f"mailto:?subject={email_subject}&body={email_body}"
    st.markdown(f"[Email This Itinerary]({mailto_link})")

    st.markdown("---")
    st.markdown("## More Ideas to Explore")
    st.markdown(
        "Below are extra suggestions we found. Feel free to add them to your plan!"
    )

    # Get hidden results for each category and show them in a friendly format
    for cat_name, cat_query in EXTRA_SEARCH_CATEGORIES.items():
        st.markdown(f"### {cat_name}")
        suggestions_data = hidden_search_for_more_ideas(cat_query)
        # If no data or not enough structure, just show a friendly fallback
        if not suggestions_data or "organic_results" not in suggestions_data:
            st.markdown("*(No extra suggestions found right now.)*")
            continue

        # Show top 3 suggestions in a user-friendly way
        items = suggestions_data["organic_results"][:3]
        for item in items:
            title = item.get("title", "Untitled")
            link = item.get("link", "#")
            snippet = item.get("snippet", "")
            st.markdown(f"**{title}**")
            st.markdown(snippet)
            st.markdown(f"[Read More]({link})\n")
        st.markdown("---")
