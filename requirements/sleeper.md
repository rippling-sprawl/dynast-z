**When prompting to load my team when selecting a league:**

## Output
server.py:                                                                                       
  - fetch_sleeper_players() — fetches the full Sleeper player database (cached 24h, it's ~5MB)
  - fetch_league_data() — fetches rosters, users, and league info from Sleeper API                 
  - build_league_rosters() — merges Sleeper roster data with your existing z-scores so each player 
  shows their aggregate value                                                                      
  - /api/league/{leagueId} — API endpoint returning the merged data                                
  - /league/{leagueId} — serves league.html                                                        
                                                                                                   
  league.html:                                                                                     
  - Fetches league data from the API and renders each team as a collapsible roster card            
  - Players use the same .player-card / .player-pos / .player-value styling from styles.css        
  - Players are split into Starters and Bench sections, sorted by z-score                  
  - Each roster header shows owner name, W-L record, total z-score, and player count               
  - First roster is expanded by default; click any header to toggle  