All done. Here's a summary of what was built:

  Files modified:                                                                                           
  - server.py — Added fetch_masters_scores() with 5-min TTL cache, /api/masters/scores endpoint, and route
  handlers for all 5 new masters views                                                                      
  - vercel.json — Added rewrites for all /masters/* routes                                                
  - scripts/nav.js — Added Masters section to navigation                                                    
                                                                                                            
  Files created:
  - styles/masters.css — Shared dark theme styles (matches ev-model look)                                   
  - scripts/masters-utils.js — Shared utilities (score formatting, localStorage helpers, fetch wrapper)     
  - views/masters/index.html — Hub page with card links to all views                                   
  - views/masters/select-golfers.html — Pick winner/top5/top10, persisted to localStorage                   
  - views/masters/leaderboard.html — Full leaderboard sorted by to-par, selected golfers highlighted blue,  
  expandable hole-by-hole scoring with color-coded cells, auto-refreshes every 11 min                       
  - views/masters/3-ball.html — Set up per-round matchup groups, persisted to localStorage                  
  - views/masters/3-ball-results.html — Live 3-ball results with win/loss coloring, auto-refreshes every 11 
  min                                                                                                       
                                                                                                            
  All routes tested and returning 200. You can start the server with python3 server.py and visit            
  localhost:8000/masters to try it out. 