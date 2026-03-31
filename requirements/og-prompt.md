I'd like to create a trade calculator for a dynasty fantasy football league.

Data sources
* https://keeptradecut.com/dynasty-rankings
** turn on "superflex" to ON
* https://fantasycalc.com/dynasty-rankings
** turn on "superflex" to ON

Model
* Players
** Each Player should have a name, position, an aggregate value, and a list of values.
** the list of values should come from the data sources list above, namespaces be the web domain
** the aggregate value should be and average of all the data sources

View
* List of Players
** each player should be listed in a vertically scrolling pane
* There should be two teams: Team A and Team B. These teams should start as an empty list
* Each Player item should display the name, position, and aggregate value

Controls
* As a user, I should be able to drag and drop each player from the "List of Players" into Team A or Team B's list. A player can only exist in one of these lists
* Whenever a player is added or removed from either team's list, the aggregate values for all players in each team should be summed independently