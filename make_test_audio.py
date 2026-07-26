import numpy as np
from scipy.io import wavfile

sr = 44100
dur = 2.0  # seconds per chord

# Note frequencies (equal temperament)
def note(n):  # n = MIDI number
    return 440.0 * 2 ** ((n - 69) / 12)

# Chord progression as MIDI note sets (root position, mid register)
# C major, G major, A minor, F major
progression = {
    "C:maj": [60, 64, 67],   # C4 E4 G4
    "G:maj": [55, 59, 62],   # G3 B3 D4
    "A:min": [57, 60, 64],   # A3 C4 E4
    "F:maj": [53, 57, 60],   # F3 A3 C4
}

def synth_chord(midis, dur, sr):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    sig = np.zeros_like(t)
    for m in midis:
        f = note(m)
        # fundamental + a few harmonics for a richer, more realistic timbre
        for h, amp in [(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)]:
            sig += amp * np.sin(2 * np.pi * f * h * t)
    # simple ADSR-ish envelope
    env = np.ones_like(t)
    a = int(0.02 * sr); r = int(0.15 * sr)
    env[:a] = np.linspace(0, 1, a)
    env[-r:] = np.linspace(1, 0, r)
    return sig * env

full = np.concatenate([synth_chord(m, dur, sr) for m in progression.values()])
full = full / np.max(np.abs(full)) * 0.9
wavfile.write("test_progression.wav", sr, (full * 32767).astype(np.int16))
print("Wrote test_progression.wav")
print("Ground truth:", " -> ".join(progression.keys()), f"({dur}s each)")
