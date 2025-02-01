import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta

# ------------------------------------------------------------------------------
# IMPORTANT:
# To use this code without changes, pin your OpenAI package version by adding the following
# line to your requirements.txt:
#
#    openai==0.28.0
#
# Alternatively, if you want to use the latest version of OpenAI, run:
#    openai migrate
# and update the code as necessary.
# ------------------------------------------------------------------------------
  
# Set API keys from Streamlit secrets
openai.api_key = st.secrets["OPENAI_API_KEY"]
SERPAPI_API_KEY = st.secrets["SERPAPI_API_KEY"]

# ------------------------------------------------------------------------------
# Function to get the next dynamic question from OpenAI based on the conversation
# ------------------------------------------------------------------------------
def get_next_question(conversation_history):
    system_prompt = (
        "You are a helpful itinerary planning assistant for a trip to Maui. "
        "Ask engaging and dynamic questions that help refine the traveler's itinerary preferences. "
        "Each question should build upon previous answers (if any) and be specific. "
        "Only ask one question at a time."
    )
    
    # Build conversation text (if any)
    conversation_text = ""
    if conversation_history:
        for turn in conversation_history:
            conversation_text += f"Q: {turn['question']}\nA: {turn['answer']}\n"
    else:
        conversation_text = "No previous conversation."
    
    user_prompt = conversation_text + "\nPlease ask the next engaging question."
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=100,
        )
        question = response.choices[0].message.content.strip()
        return question
    except Exception as e:
        st.error(f"Error generating question: {e}")
        # Fallback question in case of error:
        return "What is one thing you are most excited to experience in Maui?"

# ------------------------------------------------------------------------------
# Function to generate a full itinerary using OpenAI based on the conversation and dates
# ------------------------------------------------------------------------------
def generate_itinerary(conversation_history, start_date, end_date):
    system_prompt = (
        "You are an expert travel itinerary planner for Maui. Based on the traveler's preferences "
        "provided in the conversation below and the travel dates, generate a detailed itinerary for "
        "their trip. The itinerary should include events, restaurants, scenic spots, tours, and adventure "
        "activities. Additionally, provide a separate section called 'serpapi_queries' that contains search queries "
        "for each category (events, restaurants, scenery, tours, adventures) to fetch additional details via SerpAPI. "
        "Return the result as a valid JSON object with two keys: 'itinerary' and 'serpapi_queries'."
    )
    
    conversation_text = ""
    for turn in conversation_history:
        conversation_text += f"Q: {turn['question']}\nA: {turn['answer']}\n"
    
    user_prompt = (
        f"Travel Dates: {start_date} to {end_date}\n"
        f"Preferences:\n{conversation_text}\n\n"
        "Please generate the itinerary in JSON format."
    )
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=600,
        )
        content = response.choices[0].message.content.strip()
        # Attempt to parse the JSON output
        itinerary_data = json.loads(content)
        return itinerary_data
    except json.JSONDecodeError:
        st.error("Failed to parse itinerary JSON. Here is the raw response:")
        st.text(content)
        return None
    except Exception as e:
        st.error(f"Error generating itinerary: {e}")
        return None

# ------------------------------------------------------------------------------
# Function to call SerpAPI with error handling and retries
# ------------------------------------------------------------------------------
def call_serpapi(query, retries=3):
    base_url = "https://serpapi.com/search.json"
    params = {
        "engine": "google",
        "q": query,
        "location": "Maui, Hawaii",
        "api_key": SERPAPI_API_KEY,
    }
    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                st.warning(f"SerpAPI returned status code {response.status_code}. Retrying...")
        except Exception as e:
            st.warning(f"Error calling SerpAPI: {e}. Retrying...")
        attempt += 1
        time.sleep(2)
    st.error("Failed to fetch data from SerpAPI after multiple attempts.")
    return {}

# ------------------------------------------------------------------------------
# Initialize session state variables for conversation and itinerary generation
# ------------------------------------------------------------------------------
if "conversation" not in st.session_state:
    st.session_state.conversation = []
if "question_index" not in st.session_state:
    st.session_state.question_index = 0
if "itinerary_generated" not in st.session_state:
    st.session_state.itinerary_generated = False

# ------------------------------------------------------------------------------
# App UI: Title, description, and travel date selection
# ------------------------------------------------------------------------------
st.title("Maui Itinerary Planner")
st.markdown("Plan an exciting trip to Maui with dynamic itinerary suggestions based on your preferences.")

# Date selection using two columns
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Select Start Date", value=date.today())
with col2:
    end_date = st.date_input("Select End Date", value=date.today() + timedelta(days=7))
if start_date > end_date:
    st.error("Start date must be before end date.")

# ------------------------------------------------------------------------------
# Conversation Flow: Ask 3 dynamic questions to learn her preferences
# ------------------------------------------------------------------------------
if st.session_state.question_index < 3:
    st.header(f"Question {st.session_state.question_index + 1} of 3")
    # If no current question exists in session state, generate one
    if "current_question" not in st.session_state:
        question = get_next_question(st.session_state.conversation)
        st.session_state.current_question = question
    st.write(f"**{st.session_state.current_question}**")
    
    with st.form(key="answer_form"):
        answer = st.text_input("Your answer:")
        submit = st.form_submit_button("Submit Answer")
    if submit and answer:
        st.session_state.conversation.append({
            "question": st.session_state.current_question,
            "answer": answer
        })
        st.session_state.question_index += 1
        # Remove the current question so the next one is generated
        del st.session_state.current_question
        # Use experimental_rerun if available; otherwise, prompt a manual refresh.
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        else:
            st.write("Please refresh the page to see the next question.")

# ------------------------------------------------------------------------------
# Once 3 questions have been answered, allow itinerary generation
# ------------------------------------------------------------------------------
if st.session_state.question_index >= 3 and not st.session_state.itinerary_generated:
    st.header("Generate Your Maui Itinerary")
    if st.button("Generate Itinerary"):
        itinerary_data = generate_itinerary(st.session_state.conversation, start_date, end_date)
        if itinerary_data is not None:
            st.session_state.itinerary_generated = True
            st.session_state.itinerary_data = itinerary_data
            st.success("Itinerary generated successfully!")
        else:
            st.error("Failed to generate itinerary. Please try again.")

# ------------------------------------------------------------------------------
# Display the itinerary and fetch additional details via SerpAPI
# ------------------------------------------------------------------------------
if st.session_state.itinerary_generated:
    st.subheader("Your Dynamic Maui Itinerary")
    st.json(st.session_state.itinerary_data.get("itinerary", {}))
    
    serpapi_queries = st.session_state.itinerary_data.get("serpapi_queries", {})
    if serpapi_queries:
        st.subheader("Additional Details via SerpAPI")
        for category, query in serpapi_queries.items():
            st.markdown(f"**{category.capitalize()} Search**")
            st.write(f"Query: {query}")
            result = call_serpapi(query)
            st.json(result)
    else:
        st.info("No SerpAPI queries provided in the itinerary data.")
