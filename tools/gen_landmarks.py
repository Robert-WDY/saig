"""Generate the map landmark art with AI Centre (nano-banana-2, async jobs, idempotent by external_ref).
Usage: AIC_API_KEY=... AIC_REF_URLS=url1,url2 python tools/gen_landmarks.py lute customs ...
Output raw-<id>.png on a white background; cut it out and save web/atlas/lm-<id>.webp."""
import json, sys, time, urllib.request
B = "https://aicentre2.sligenai.cn:8443"
import os
K = os.environ["AIC_API_KEY"]  # AI Centre key: keep it out of the repo
REF = os.environ["AIC_REF_URLS"].split(",")  # uploaded crops of the painted sprite (tower, campus) as style references
STYLE = ("Isometric 3D miniature diorama game asset in exactly the same art style as the reference images: "
         "warm saturated colors, soft clay-like lighting, crisp clean edges, small trees, a rounded grass-and-earth "
         "base plate with an orange-tan soil rim, viewed from the same 3/4 isometric angle. One single object, centered, "
         "fully visible with margin around it, nothing cropped. No text, no labels, no people, no border. "
         "Isolated on a plain pure white background (#FFFFFF), no shadow on the background. Subject: ")
SUBJECTS = {
  "customs": "Jianghan Customs House (江汉关) in Wuhan: a grey-white neoclassical stone building with columns and a tall square clock tower with a clock face, beside a small strip of river.",
  "lute": "Guqin Terrace (古琴台) in Wuhan: a small traditional Chinese pavilion with red pillars and grey upturned tiled roof on a stone terrace, a guqin zither table inside, willow and pine trees around.",
  "temple": "Guiyuan Buddhist Temple (归元寺) in Wuhan: a yellow-walled Chinese temple hall with double-eaved dark tiled roof, red doors, a bronze incense burner in the courtyard and ginkgo trees.",
  "lake": "East Lake (东湖) in Wuhan: a three-tiered red Chinese pavilion (行吟阁) on a little island in turquoise lake water, a zigzag stone bridge, lotus leaves and a willow tree.",
  "blossom": "Moshan cherry blossom garden at East Lake, Wuhan: a gentle green hill covered with pink cherry blossom trees and a small red pavilion on top, a winding path.",
  "hust": "Huazhong University of Science and Technology campus in Wuhan: a modern cream-colored main building with tall windows, surrounded by many lush dense green trees (a forest campus) and a lawn.",
  "museum": "Hubei Provincial Museum in Wuhan: a grand modern building with a huge sweeping Chu-style high hip roof, and in front a wooden frame of ancient bronze chime bells (编钟).",
  "noodles": "Hubu Alley (户部巷) food street in Wuhan: a red traditional paifang archway gate over a lively snack street with small shops and red lanterns, a big steaming bowl of hot dry noodles (热干面) in front.",
  "lanterns": "Jiqing Street (吉庆街) night food street in Wuhan: two rows of old two-story wooden shophouses with many glowing red lanterns strung across, small outdoor tables.",
  "redhouse": "The Red House, Wuchang Uprising Memorial of the 1911 Revolution (辛亥革命武昌起义纪念馆) in Wuhan: a red-brick two-story western-style building with a central tower and dark dome, white window frames, a flag pole.",
  "optics": "Optics Valley Square (光谷广场) in Wuhan: a modern futuristic ring-shaped sculpture with orange spiral at the center of a roundabout, surrounded by glass high-rise towers.",
  "tower": "Wuhan Center skyscraper (武汉中心): a very tall slender blue glass supertall tower with a tapered crown, with a few smaller glass buildings around its base.",
  "villa": "Lihuangpi Road (黎黄陂路) historic street in Hankou, Wuhan: an elegant European-style colonial villa with red tiled roof, cream walls, arched windows and verandas, plane trees lining the street.",
  "riverbank": "Hankou Riverside Park (汉口江滩) in Wuhan: wide stone steps descending to the broad Yangtze river, a white ferry boat on the water, green park lawns and trees along the bank.",
}
import urllib.error
def req(method, path, body=None, idem=None):
    headers = {"Authorization": "Bearer " + K, "Content-Type": "application/json"}
    if idem: headers["Idempotency-Key"] = idem
    for attempt in range(8):
        r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body else None, headers=headers)
        try:
            return json.load(urllib.request.urlopen(r, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            print("429", e.read()[:200], flush=True); time.sleep(15 * (attempt + 1))
    raise RuntimeError("rate limited")
jobs = {}
for key in sys.argv[1:]:
    j = req("POST", "/v1/image-generations/jobs", {"model": "nano-banana-2", "prompt": STYLE + SUBJECTS[key],
             "reference_image_urls": REF, "aspect_ratio": "1:1", "image_size": "1K", "external_ref": "saig-landmark-" + key}, idem="saig-landmark-" + key)
    jobs[key] = j["job_id"]; print("submitted", key, flush=True)
done = {}
deadline = time.time() + 900
while len(done) < len(jobs) and time.time() < deadline:
    time.sleep(8)
    for key, jid in jobs.items():
        if key in done: continue
        s = req("GET", "/v1/image-generations/jobs/" + jid)
        if s["status"] == "succeeded":
            urllib.request.urlretrieve(s["result_urls"][0], f"raw-{key}.png"); done[key] = "ok"; print("done", key, flush=True)
        elif s["status"] in ("failed", "cancelled"):
            done[key] = "failed"; print("FAILED", key, s.get("error"), flush=True)
print(done)
