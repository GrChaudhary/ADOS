import os
import sys

# Ensure the root folder of the project is in the Python search path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Manually load .env into os.environ before importing client
env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

from knowledge.tts_client import tts_client

SCENE_VOICEOVERS = {
    "voice_final_scene1": (
        "At the Nova Motors EV plant, when a bore tolerance breach occurs on a motor housing, "
        "traditional resolution takes hours of manual coordination across engineers, managers, and buyers. "
        "Novus ADOS solves this through a unified 6-Layer Enterprise Decision Stack: "
        "from Layer 1 Event Envelope up through Layer 6 Executive Intel."
    ),
    "voice_final_scene2": (
        "Phase one detects the defect via micro inch CAD tolerance checks. "
        "Next, the Causal Isolation agent combines Bayesian causal graph edges with local LLM reasoning over historical evidence, "
        "evaluating spindle vibration, tool wear, supplier material batches, and ambient humidity, ranked strictly by probability."
    ),
    "voice_final_scene3": (
        "Rather than guessing, ADOS generates and ranks mitigation options with real financial data. "
        "Running Monte Carlo simulations, it calculates exact speed parameter adjustments versus part replacement, "
        "projecting precise downtime minutes, component costs, and quality risk scores for every candidate."
    ),
    "voice_final_scene4": (
        "The distinctive bet of ADOS is governed autonomy. "
        "The system evaluates financial exposure multiplied by confidence and capability risk. "
        "Low risk, high confidence actions execute autonomously at Tier 0. "
        "Higher exposure decisions automatically trigger Tier 1 or Tier 2 human approval gates, preserving executive control."
    ),
    "voice_final_scene5": (
        "Unlike decision support demos that stop at recommendations, ADOS actually executes. "
        "Upon approval, the governed ServiceNow connector triggers live Table API calls to create a genuine ServiceNow incident and change request, "
        "while reserving SAP replacement inventory in real time."
    ),
    "voice_final_scene6": (
        "Finally, ADOS feeds resolution outcomes back into the Bayesian causal model so root cause accuracy improves over time. "
        "Every decision is fully audited. "
        "The Executive layer proves the business impact: reducing MTTR from hours to minutes, boosting autonomy index, and protecting plant revenue."
    )
}

def main():
    # Target directory in the Remotion public folder
    target_dir = "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/Videos/ados-video/public/voiceover"
    os.makedirs(target_dir, exist_ok=True)
    
    print("Checking TTS configuration...")
    if not tts_client.is_configured():
        print("ERROR: IBM Watson Text to Speech is not properly configured. Check env variables.")
        sys.exit(1)
        
    print("Synthesizing master voiceovers for 6 chapters...")
    for filename, text in SCENE_VOICEOVERS.items():
        print(f"Generating voice for {filename}...")
        res = tts_client.synthesize(text, voice="en-US_AllisonV3Voice", accept="audio/mp3")
        
        if res.get("status") == "live":
            audio_bytes = res["audio_bytes"]
            dest_path = os.path.join(target_dir, f"{filename}.mp3")
            with open(dest_path, "wb") as f:
                f.write(audio_bytes)
            print(f"Successfully saved to {dest_path}")
        else:
            print(f"ERROR generating {filename}: {res.get('error')}")
            sys.exit(1)

    print("Master TTS generation completed successfully!")

if __name__ == "__main__":
    main()
