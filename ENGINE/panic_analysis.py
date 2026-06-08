#Install python -m textblob.download_corpora
from textblob import TextBlob
import re

EMERGENCY_KEYWORDS = {
    "help",
    "fire",
    "flood",
    "earthquake",
    "collapse",
    "explosion",
    "ambulance",
    "blood",
    "panic",
    "dead",
    "dying",
    "trapped",
    "accident",
    "storm",
    "emergency",
    "injured",
    "rescue",
    "hospital",
    "danger",
}

def calculate_sentiment_score(messages):
    if not messages:
        return 0.0
    total = 0.0
    for msg in messages:
        polarity = TextBlob(msg).sentiment.polarity
        negative_score = (1 - ((polarity + 1) / 2))
        total += negative_score
    avg = total / len(messages)
    return round(avg * 100, 2)

def calculate_emergency_keyword_score(messages):
    if not messages:
        return 0.0
    keyword_hits = 0
    total_words = 0
    for msg in messages:
        words = re.findall(
            r"\w+",
            msg.lower()
        )
        total_words += len(words)
        for word in words:
            if word in EMERGENCY_KEYWORDS:
                keyword_hits += 1
    if total_words == 0:
        return 0.0
    ratio = keyword_hits / total_words
    return min( ratio * 1500, 100 )