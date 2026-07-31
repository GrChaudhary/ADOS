import cv2
import os

video_path = "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/Videos/Screen Recording 2026-07-28 at 5.34.30 PM.mov"
out_dir = "/Users/gauravchaudhary/.gemini/antigravity-ide/brain/8a7f9458-7fd3-4f67-a3aa-1875b1e13314"

cap = cv2.VideoCapture(video_path)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS)

print(f"Total frames: {total_frames}, FPS: {fps}")

# Extract 4 evenly spaced frames
frame_indices = [
    int(total_frames * 0.1),
    int(total_frames * 0.35),
    int(total_frames * 0.65),
    int(total_frames * 0.9)
]

for idx, f_num in enumerate(frame_indices):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_num)
    ret, frame = cap.read()
    if ret:
        out_file = os.path.join(out_dir, f"spine_ref_frame_{idx+1}.png")
        cv2.imwrite(out_file, frame)
        print(f"Saved {out_file}")

cap.release()
