"""Render the offline voice clips once at build time, in 3 languages (spec FR-6.2).

Output: voice_assets/<lang>/<file>.wav  for lang in en, ta, hi.

Prefers Piper (high quality, offline) — pass a per-language Piper model dir or
rely on PIPER_MODEL_<LANG> env vars. Falls back to pyttsx3 (English only, low
quality). If neither can do Tamil/Hindi on your machine, record the WAVs yourself
and drop them in the matching voice_assets/<lang>/ folder — the filenames below
are all that matter.

    python scripts/render_voice.py
    PIPER_MODEL_TA=/path/ta.onnx PIPER_MODEL_HI=/path/hi.onnx python scripts/render_voice.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "voice_assets"

# filename -> text, per language. Filenames are identical across languages.
PHRASES = {
    "en": {
        "registered.wav": "Registered.",
        "language_selected.wav": "English selected.",
        "welcome.wav": "Welcome. Please stand in front of the camera, or place your finger.",
        "registration_active.wav": "Registration mode active. Please stand in front of the camera.",
        "registered_ok.wav": "Registered successfully.",
        "registration_failed.wav": "Registration unsuccessful. Please try again.",
        "come_closer.wav": "Please come closer.",
        "stand_back.wav": "Please stand back a little.",
        "look_straight.wav": "Please look straight ahead.",
        "look_up.wav": "Please tilt your head up.",
        "look_down.wav": "Please tilt your head down.",
        "confirm.wav": "Recognised. Please hold still and follow the instructions.",
        "blink.wav": "Please blink your eyes.",
        "turn_left.wav": "Please turn your head to the left.",
        "turn_right.wav": "Please turn your head to the right.",
        "verify_ok.wav": "Good.",
        "granted_face.wav": "Access granted by face recognition.",
        "denied_face.wav": "Access denied by face recognition.",
        "denied_spoof.wav": "Movement not detected. Please try again.",
        "granted_finger.wav": "Access granted by fingerprint.",
        "denied_finger.wav": "Access denied by fingerprint. Please try again.",
    },
    "ta": {
        "registered.wav": "பதிவு செய்யப்பட்டது.",
        "language_selected.wav": "தமிழ் தேர்ந்தெடுக்கப்பட்டது.",
        "welcome.wav": "வரவேற்கிறோம். கேமராவின் முன் நில்லுங்கள் அல்லது விரலை வைக்கவும்.",
        "registration_active.wav": "பதிவு பயன்முறை செயலில் உள்ளது. கேமராவின் முன் நில்லுங்கள்.",
        "registered_ok.wav": "வெற்றிகரமாக பதிவு செய்யப்பட்டது.",
        "registration_failed.wav": "பதிவு தோல்வியடைந்தது. மீண்டும் முயற்சிக்கவும்.",
        "come_closer.wav": "தயவுசெய்து அருகில் வாருங்கள்.",
        "stand_back.wav": "தயவுசெய்து சற்று பின்னால் நில்லுங்கள்.",
        "look_straight.wav": "நேராக பாருங்கள்.",
        "look_up.wav": "தலையை மேலே சாய்க்கவும்.",
        "look_down.wav": "தலையை கீழே சாய்க்கவும்.",
        "confirm.wav": "அடையாளம் காணப்பட்டது. அசையாமல் இருந்து அறிவுறுத்தல்களைப் பின்பற்றவும்.",
        "blink.wav": "தயவுசெய்து கண்களை சிமிட்டவும்.",
        "turn_left.wav": "தயவுசெய்து தலையை இடதுபுறம் திருப்பவும்.",
        "turn_right.wav": "தயவுசெய்து தலையை வலதுபுறம் திருப்பவும்.",
        "verify_ok.wav": "சரி.",
        "granted_face.wav": "முக அங்கீகாரத்தின் மூலம் அனுமதி வழங்கப்பட்டது.",
        "denied_face.wav": "முக அங்கீகாரத்தின் மூலம் அனுமதி மறுக்கப்பட்டது.",
        "denied_spoof.wav": "அசைவு கண்டறியப்படவில்லை. மீண்டும் முயற்சிக்கவும்.",
        "granted_finger.wav": "கைரேகை மூலம் அனுமதி வழங்கப்பட்டது.",
        "denied_finger.wav": "கைரேகை மூலம் அனுமதி மறுக்கப்பட்டது. மீண்டும் முயற்சிக்கவும்.",
    },
    "hi": {
        "registered.wav": "पंजीकृत।",
        "language_selected.wav": "हिन्दी चुनी गई।",
        "welcome.wav": "स्वागत है। कृपया कैमरे के सामने खड़े हों, या अपनी उंगली रखें।",
        "registration_active.wav": "पंजीकरण मोड सक्रिय है। कृपया कैमरे के सामने खड़े हों।",
        "registered_ok.wav": "सफलतापूर्वक पंजीकृत।",
        "registration_failed.wav": "पंजीकरण असफल। कृपया पुनः प्रयास करें।",
        "come_closer.wav": "कृपया पास आएँ।",
        "stand_back.wav": "कृपया थोड़ा पीछे हटें।",
        "look_straight.wav": "कृपया सीधे देखें।",
        "look_up.wav": "कृपया सिर ऊपर करें।",
        "look_down.wav": "कृपया सिर नीचे करें।",
        "confirm.wav": "पहचान हो गई। कृपया स्थिर रहें और निर्देशों का पालन करें।",
        "blink.wav": "कृपया अपनी आँखें झपकाएँ।",
        "turn_left.wav": "कृपया अपना सिर बाईं ओर घुमाएँ।",
        "turn_right.wav": "कृपया अपना सिर दाईं ओर घुमाएँ।",
        "verify_ok.wav": "ठीक है।",
        "granted_face.wav": "चेहरे की पहचान से प्रवेश स्वीकृत।",
        "denied_face.wav": "चेहरे की पहचान से प्रवेश अस्वीकृत।",
        "denied_spoof.wav": "हलचल नहीं मिली। कृपया पुनः प्रयास करें।",
        "granted_finger.wav": "फ़िंगरप्रिंट से प्रवेश स्वीकृत।",
        "denied_finger.wav": "फ़िंगरप्रिंट से प्रवेश अस्वीकृत। कृपया पुनः प्रयास करें।",
    },
}


def render_piper(text: str, dest: Path, model: str) -> bool:
    if not model or not shutil.which("piper"):
        return False
    p = subprocess.run(["piper", "--model", model, "--output_file", str(dest)],
                       input=text.encode("utf-8"), capture_output=True)
    return p.returncode == 0 and dest.exists()


def render_pyttsx3(text: str, dest: Path) -> bool:
    try:
        import pyttsx3
    except Exception:
        return False
    eng = pyttsx3.init()
    eng.save_to_file(text, str(dest))
    eng.runAndWait()
    return dest.exists()


def main():
    for lang, clips in PHRASES.items():
        model = os.environ.get(f"PIPER_MODEL_{lang.upper()}")
        dest_dir = OUT / lang
        dest_dir.mkdir(parents=True, exist_ok=True)
        for fname, text in clips.items():
            dest = dest_dir / fname
            ok = render_piper(text, dest, model) or (lang == "en" and render_pyttsx3(text, dest))
            print(("[done] " if ok else "[FAIL] ") + str(dest))
    print("\nTamil/Hindi need a Piper voice (PIPER_MODEL_TA / PIPER_MODEL_HI) or your own WAVs.\n"
          "Drop hand-recorded clips in voice_assets/<lang>/ using the filenames above if TTS fails.")


if __name__ == "__main__":
    main()
