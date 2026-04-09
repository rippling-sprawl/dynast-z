Context
- During The Masters golf tournament, I want to be able to track "my golfers" against different criteria. The main tracker would highlight my selected players vs the rest of the leaderboard across the whole tournament. Another primary view would be tracking several of my individual golfers vs a select number of other golfers.

Views within "/views"
- "/masters":
	- Provides links to each of the following views and "ev-model". All views within "/masters" should be linked, ideally automatically as more views are added.
- "/select-golfers":
	- Select my golfers for the tournament
	- Select winner, finish top 5 on the leaderboard, finish top 10 on the leaderboard
- "/3-ball":
	- Select my golfers for a given round (rounds 1 through 4), then select 1 or 2 opposing golfers
	- the lower round score is the winning golfer
- "/3-ball-results"
- "/leaderboard":
	- View leaderboard
	- All golfers for the tournament, showing their current round first, with a way to see past rounds as well

For select-golfers and 3-ball, my selections should persist in local storage indefinitely. A manual clearing of the data can happen later, but it's not a feature at this time.


Styling
- the /views/masters/*, and in particular the leaderboard, should generally follow the styling of /views/masters/ev-model

Data
- The data for each golfer and their scoring for the tournament should come from the masters website. In particular this json: https://www.masters.com/en_US/scores/feeds/2026/scores.json
- I've had issues with user agent detection with this json before, so that may present a challenge.
- The TTL on this request should be 5 minutes
- The "leaderboard" and "3-ball-results" should refresh in-page without user intervention every 11 minutes

Examples
- For the Leaderboard: I built a version of this feature in Google Sheets (see attached). My selected golfers are highlighted blue on the left. They are sorted by aggregate score in ascending order (because lower is better in golf). Each of their rounds are listed with every hole score relative to par (0 is par, -1 is a birdie, +1 is a bogey, etc)
- for the 3-ball-results: I built this in Google Sheets too (see attached). My selected 3-ball golfers are in green or red, while the opponents are not highlighted. Each "grouping" is surrounded by thick black borders. It lists my golfer, his current round score, and what hole he's thru. His current round is compared to the other 2 golfers in his grouping as to whether he's winning out of those 3.