Candidate Name: SPOORTHI J


Scenario Chosen: Community Safety & Digital Wellness 


Estimated Time Spent: 5-6 HOURS


Quick Start: 

● Prerequisites:
Python 3.10+
A free Groq API key — get one at console.groq.com/keys



● Run Commands: 
1. Install requirements
   pip install -r requirements.txt

2. Set your API key
   cp .env.example .env    
   $env:GROQ_API_KEY="gsk_your_key_here"
   
3. Start the server
   cd backend
   uvicorn main:app --reload

4. Open API docs
   http://127.0.0.1:8000/docs



● Test Commands: pytest tests/ -v



AI Disclosure: 
● Did you use an AI assistant (Copilot, ChatGPT, etc.)?

Yes — Claude (Anthropic) was used throughout the project.



● How did you verify the suggestions?

Every generated code block was read line by line before being added to the project. The filter logic (not c.is_noise and c.confidence >= threshold) was traced manually against a table of test cases before writing the tests. The fallback confidence value of 0.65 was a deliberate decision made after reviewing what the generated code produced — the original suggestion used 0.75, which was changed because it sat too close to the "Likely" confidence band and would have made fallback cards indistinguishable from real medium-confidence AI output. Each endpoint was tested live via Swagger UI and the actual responses were checked against expected behaviour before moving on.



● Give one example of a suggestion you rejected or changed:  Tradeoffs & Prioritization:

One example of a suggestion rejected or changed: The AI initially suggested storing only cards that passed the confidence filter — writing clean data and discarding the rest. This was rejected. The final implementation stores every card regardless of quality and filters at read time in /digest. The reason: if you discard low-confidence cards at write time, you lose the audit trail. You can never answer "did the system receive this report?" or "what did the AI think of it?" Keeping everything and filtering at read time also means the threshold can be changed without touching stored data — a card withheld today at 0.6 would surface if you lowered the threshold to 0.5 tomorrow.



● What did you cut to stay within the 4–6 hour limit?

What was cut to stay within the 4–6 hour limit?
Authentication on /all and /clear — these are admin endpoints that should be behind an API key or JWT. Currently they are open. Anyone who knows the URL can wipe the database.
Concurrent write safety — the JSON file database uses read-modify-write without a lock. Two simultaneous POST requests could cause one card to be lost. A production system would use SQLite at minimum.
Deduplication — if the same scam is reported ten times, ten cards are stored and all ten appear in /digest. There is no logic to detect that id: abc and id: xyz are describing the same incident.
Rate limiting — there is nothing stopping a single user from flooding the system with reports.
A frontend — the system is tested entirely through Swagger UI. A resident-facing interface was descoped to focus on the pipeline correctness.



● What would you build next if you had more time? 

1. Deduplication — cluster cards by semantic similarity so the same incident reported multiple times surfaces as one alert with a report count, not ten separate cards. This also increases confidence organically: five independent reports of the same scam should push confidence higher than one.
2. Authentication — JWT-based auth on admin endpoints, rate limiting on /report.
3. Persistent storage — swap db.py for SQLite. The interface is already isolated to one file so this is a contained change.
4. Confidence drift logging — track how the AI's confidence scores distribute over time. If the average starts dropping, it likely means the model is being used outside its training distribution and the system prompt needs updating.
5. Human review queue — cards between confidence 0.4 and 0.6 (currently silently withheld) should surface in a moderation UI where a human can approve or reject them before they reach residents.



● Known limitations:

Fallback cards pollute the digest — if the LLM is offline, the keyword-based fallback assigns confidence: 0.65 to every report regardless of actual content. A vague report and a specific report look identical in the digest during an outage. This was acceptable for a prototype but would need a secondary scoring layer in production.
LLM output is non-deterministic — the same report submitted twice may return different confidence scores. Temperature is set to 0.2 to reduce this, but it is not eliminated. The system does not average multiple passes.
Model deprecation — Groq decommissions models without long notice periods. The model name is a single constant in ai_engine.py but there is no automatic fallback to an alternative model if the primary is retired. This happened during development and caused several hours of fallback-only operation before being caught.
Confidence is self-reported by the LLM — the model is instructed to be honest about uncertainty but there is no external calibration. The 0.6 threshold was chosen based on observed output during testing, not a statistically validated calibration set.
English only — the system prompt and fallback keywords assume English input. Reports in Kannada, Hindi, or Hinglish will either be misclassified or returned with artificially low confidence.
