"""Quick test to validate the improved _CONFAB_CLAIM_RE."""
import re

_CONFAB_CLAIM_RE = re.compile(
    r"(?:"
    # Direct action verbs (past tense)
    r"turned\s+(?:off|on|the)|switched\s+(?:off|on|the)|"
    r"powered\s+(?:off|on|down|up)|shut\s+(?:off|down|it)|"
    # State claims ("lights are now off", "should be off")
    # Note: "on" and "set" are excluded from the bare is/are pattern
    # because they cause too many false positives ("meeting is on Monday",
    # "alarm is set for 7am"). They are matched only with "now" qualifier
    # or (for "set") when followed by "to" indicating a value assignment.
    r"(?:is|are|should\s+be)\s+(?:now\s+)?(?:off|locked"
    r"|unlocked|open(?:ed)?|closed|armed|disarmed"
    r"|adjusted|dimmed)|"
    # "is/are now on" and "is/are now set" — require "now" to avoid
    # false positives like "the meeting is on Monday"
    r"(?:is|are|should\s+be)\s+now\s+(?:on|set)|"
    # "should be on/off now" (word order variant)
    r"should\s+be\s+(?:on|off)\s+now|"
    # "is set to <value>" — device value assignment, not "is set for tomorrow"
    r"(?:is|are)\s+set\s+to\b|"
    # Completion claims ("it is done", "taken care of")
    r"(?:it\s+is|it's|that's)\s+done|"
    r"taken\s+care\s+of|"
    # "all set" only at end of text or before punctuation/dash,
    # not "all set for tomorrow"
    r"all\s+set(?:\s*[.!,;\u2014\u2013\-]|\s*$)|"
    r"all\s+done|"
    # First-person past claims ("I've turned...", "I have set...")
    r"i've\s+(?:turned|set|locked|unlocked|opened|closed|"
    r"adjusted|activated|dimmed|toggled|armed|disarmed)|"
    r"i\s+have\s+(?:turned|set|locked|unlocked|opened|closed|"
    r"adjusted|activated|dimmed|toggled|armed|disarmed)|"
    # Specific device action verbs
    r"\bcycled\b|adjusted\s+the|dimmed\s+the|brightened\s+the|"
    r"activated\s+the|deactivated\s+the|"
    r"locked\s+the|unlocked\s+the|"
    r"opened\s+the|closed\s+the|"
    r"set\s+the\s+.{1,30}\s+to"
    r")",
    re.IGNORECASE,
)

# Test false positives - SHOULD NOT match
false_positives = [
    "The current temperature outside is 72 degrees.",
    "Your schedule is set for tomorrow.",
    "You are all set for your appointment.",
    "That should have been obvious.",
    "I corrected the spelling mistake.",
    "The weather is on the warm side.",
    "Here is the information you requested.",
    "The meeting is on Monday.",
    "Your alarm is set for 7am.",
    "The status is on its way.",
    "Good evening. How may I help?",
    "Sure, how can I help?",
    "Here are your calendar events.",
    "I don't have access to that device.",
    "Your schedule for today looks clear.",
    "I'll need to check on that.",
]

# Test true positives (should match)
true_positives = [
    # Direct action verbs
    "I've turned on the kitchen light.",
    "I turned off the fan.",
    "Turned the light on for you.",
    "Turned the lamp off.",
    "I've turned it on for you.",
    "I have adjusted the thermostat.",
    "The system cycled the breaker.",
    # JARVIS-style phrasings
    "Very well. The basement lights are now off.",
    "The lights are off.",
    "Done - kitchen lights are now on.",
    "The thermostat is set to 72.",
    "It is done. The basement lights are now off.",
    "That's done. All lights are off.",
    "The door is now locked.",
    "All set - the garage is closed.",
    "It's done.",
    "Adjusted the thermostat for you.",
    "The fan should be on now.",
    "Switched off the bedroom lights.",
    "Taken care of - all lights are off.",
    "Dimmed the living room lights.",
    "Activated the scene for you.",
    # "is/are now on/set"
    "The lights are now on.",
    "The thermostat is now set.",
    # all done
    "All done.",
    "All done, lights are off.",
    # "that should have" with action context
    "That should have corrected the issue.",
]

print("=== FALSE POSITIVES (should NOT match but do) ===")
fp_count = 0
for text in false_positives:
    match = _CONFAB_CLAIM_RE.search(text)
    if match:
        print(f"  FAIL FP: {repr(text)} -> matched {repr(match.group())}")
        fp_count += 1
    else:
        print(f"  OK: {repr(text)} -> no match")

print()
print("=== TRUE POSITIVES (should match) ===")
fn_count = 0
for text in true_positives:
    match = _CONFAB_CLAIM_RE.search(text)
    if match:
        print(f"  OK: {repr(text)} -> matched {repr(match.group())}")
    else:
        print(f"  FAIL FN: {repr(text)} -> no match (FALSE NEGATIVE)")
        fn_count += 1

print()
print(f"Total false positives: {fp_count}/{len(false_positives)}")
print(f"Total false negatives: {fn_count}/{len(true_positives)}")
