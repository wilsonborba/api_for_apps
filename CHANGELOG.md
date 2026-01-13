## [unreleased]

### 🚀 Features

- *(auth)* Implement basic API key auth with protected and open endpoints
- *(routes)* Organized the initial structures for both entities app and user
- *(db)* Created initial structure for user db connections
- *(db)* First query into db from api implemented
- *(db)* Improved query of all user with firebase + db integration
- *(sync)* Created services/handlers/routes for login and sign
- *(db)* Improved query return for login adding firebase user info
- *(auth)* Added a limit rate and hashpassword
- *(sync)* Created initial endpoint for auth apps
- *(auth)* Added a local proxy apps services redirect
- *(sync)* Initial communication with righ sync/auth process
- *(sync)* Implemented a user id redirect for localhost api
- *(app)* Fixed proxy timeout
- *(user)* Patch some info about the user
- *(user)* Created new routes info about user
- *(proxy)* Improved to return the same code status proxied
- *(auth)* Changed a hardcode string that was wrong

### 🐛 Bug Fixes

- *(db)* Adjusted load token from json
- *(auth)* No api key on headers
- *(auth)* Try block to avoid 500 code
- *(proxy)* Fixed query params  for quiz api
- *(routes)* Returning sucessful parsed data into string
- *(route)* Fixed parsing token
- *(handlers)* Added some changes that i forgot
- *(auth)* Forgot to add the accesslevel 3

### ⚙️ Miscellaneous Tasks

- *(env)* Created initial env struct for api/middleware
- *(env)* Created initial route for testing
- *(docs)* Missed commit the changelog file
- *(release)* Adjusted the bash run application for prod and dev
- *(release)* Created a install bash script for systemctl service
