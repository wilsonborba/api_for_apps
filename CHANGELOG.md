# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-08

### 🚀 Features

- *(auth)* Implement basic API key auth with protected and open endpoints ([`49cc331`](https://github.com/wilsonborba/api_for_apps/commit/49cc33180eec799d10e0610eed9ee0e48f11a492))
- *(routes)* Organized the initial structures for both entities app and user ([`2dbdfb3`](https://github.com/wilsonborba/api_for_apps/commit/2dbdfb3da26e6b0898a0af6ffec05c5a56c9746b))
- *(db)* Created initial structure for user db connections ([`0a28314`](https://github.com/wilsonborba/api_for_apps/commit/0a283147239a1a7dd1407e5ea5560d94a321d52d))
- *(db)* First query into db from api implemented ([`be23328`](https://github.com/wilsonborba/api_for_apps/commit/be233289a94a49af97b679f9b624b8f2cbb27610))
- *(db)* Improved query of all user with firebase + db integration ([`7249e1f`](https://github.com/wilsonborba/api_for_apps/commit/7249e1f8cab61b0f8c173c9951532bd03ac0b56f))
- *(sync)* Created services/handlers/routes for login and sign ([`5d96c2c`](https://github.com/wilsonborba/api_for_apps/commit/5d96c2cdf86745bd36af8266fdef21e21f2fdd31))
- *(db)* Improved query return for login adding firebase user info ([`ebbd7e4`](https://github.com/wilsonborba/api_for_apps/commit/ebbd7e452aae5828e6c7b3c412f5472ccbc64773))
- *(auth)* Added a limit rate and hashpassword ([`ab3103b`](https://github.com/wilsonborba/api_for_apps/commit/ab3103bb611d8002ef84941b827caf7c8cf0e5cc))
- *(sync)* Created initial endpoint for auth apps ([`80c8e42`](https://github.com/wilsonborba/api_for_apps/commit/80c8e424c3bfe073c91d34171bdcbf6823756015))
- *(auth)* Added a local proxy apps services redirect ([`10e061c`](https://github.com/wilsonborba/api_for_apps/commit/10e061c9a9bc3aa6acd75ff2f22e953f99ce8e97))
- *(sync)* Initial communication with righ sync/auth process ([`fd0aa98`](https://github.com/wilsonborba/api_for_apps/commit/fd0aa989252d62ab5b8ece126bd6029d0085d0ca))
- *(sync)* Implemented a user id redirect for localhost api ([`aa67af0`](https://github.com/wilsonborba/api_for_apps/commit/aa67af032cfc2ff06d03025a4a179ca22af85428))
- *(app)* Fixed proxy timeout ([`7490c57`](https://github.com/wilsonborba/api_for_apps/commit/7490c570e3e26b1e6b051c7ef4956c533913ee69))
- *(user)* Patch some info about the user ([`7c8dee4`](https://github.com/wilsonborba/api_for_apps/commit/7c8dee4f8f978950dc73413acea3dab64fd09b40))
- *(user)* Created new routes info about user ([`add6e62`](https://github.com/wilsonborba/api_for_apps/commit/add6e62ec40eb3a9247ee9a17fce115912d48671))
- *(proxy)* Improved to return the same code status proxied ([`a4f8f6b`](https://github.com/wilsonborba/api_for_apps/commit/a4f8f6b4246400f73b868fb61d4a66e685456331))
- *(auth)* Changed a hardcode string that was wrong ([`e4c8d69`](https://github.com/wilsonborba/api_for_apps/commit/e4c8d69e7815999db1ac1edfd517742dcc1eb7a6))
- *(routes)* Added public route allow list for api proxy ([`e58f085`](https://github.com/wilsonborba/api_for_apps/commit/e58f08588543bf202a8506e7df3c280ca88c74ac))
- *(auth)* Add Supabase session exchange endpoint ([`1350152`](https://github.com/wilsonborba/api_for_apps/commit/1350152603da19c63760c3a7a42e01624510d709))
- *(auth)* Streamline auth flow and add error reporting\n\nRefs #5\nRefs #6\nRefs #7\nRefs #8 ([`f5d70ac`](https://github.com/wilsonborba/api_for_apps/commit/f5d70acf6a3d13c249a877aea0cc7e8a31bea9ab))
- *(auth)* Merge backend-driven auth and report intake\n\nCloses #5\nCloses #6\nCloses #7\nCloses #8 ([`7bc35e4`](https://github.com/wilsonborba/api_for_apps/commit/7bc35e412ba6a8724a465dc540aa1e90e71dc90d))
- *(dal)* Add Alembic migrations ([`cd6fffe`](https://github.com/wilsonborba/api_for_apps/commit/cd6fffe6a93b165b0cd51281322cb824dc5377fc))
- *(waitlist)* Add extensible public route gateway ([`391ca00`](https://github.com/wilsonborba/api_for_apps/commit/391ca00d4143f633282378cbb6858c25718c5411))
- *(support)* Add cross-app support ticket system ([`e3b5d04`](https://github.com/wilsonborba/api_for_apps/commit/e3b5d0447e4982abf96f0de63934e62d68bac9db))
- *(support)* Wire real FSM upload for ticket attachments ([`34ee6c3`](https://github.com/wilsonborba/api_for_apps/commit/34ee6c35c9c7953ef959bab1de98226774f76b71))
- *(support)* Implement admin authorization via existing access_level ([`a451f5f`](https://github.com/wilsonborba/api_for_apps/commit/a451f5fa6700870c3335626144891675cc4b0767))
- *(proxy)* Add cortex_api proxy with client app attestation ([`69883e1`](https://github.com/wilsonborba/api_for_apps/commit/69883e1404625b68f32dbf119e9e69a569fd64b9))
- *(docs)* Replace Swagger with branded Scalar API reference at /docs ([`cdd1bb7`](https://github.com/wilsonborba/api_for_apps/commit/cdd1bb7f1f614a9f5e49bf5db61e31ddd835e2bd))
- *(telemetry)* Client error ingestion pipeline with CouchDB persistence and Redis rate limiting (#22) ([`3c40b62`](https://github.com/wilsonborba/api_for_apps/commit/3c40b626066e313db4935aa9016461de6c315fb0))

### 🐛 Bug Fixes

- *(db)* Adjusted load token from json ([`98ee44b`](https://github.com/wilsonborba/api_for_apps/commit/98ee44b8527bf80a31bbd8dede84cc6c7834c73f))
- *(auth)* No api key on headers ([`296a68c`](https://github.com/wilsonborba/api_for_apps/commit/296a68c13f9b8c6220439d070fb5cfc8c22198fd))
- *(auth)* Try block to avoid 500 code ([`5e6b2a2`](https://github.com/wilsonborba/api_for_apps/commit/5e6b2a22024b1b4147b9c6fd4291306123241bbb))
- *(proxy)* Fixed query params  for quiz api ([`fb000ac`](https://github.com/wilsonborba/api_for_apps/commit/fb000ac29977ade7bc2124aa0a8592b90db50e2e))
- *(routes)* Returning sucessful parsed data into string ([`7dba907`](https://github.com/wilsonborba/api_for_apps/commit/7dba9075ffb99c26d478530ad8e046245fabbfce))
- *(route)* Fixed parsing token ([`cd201c2`](https://github.com/wilsonborba/api_for_apps/commit/cd201c22f9cf23935d040d92196fc46a9fb7c6c6))
- *(handlers)* Added some changes that i forgot ([`a7ffd35`](https://github.com/wilsonborba/api_for_apps/commit/a7ffd3540cc2b14fd11ed8ff216b0d22cedcc68d))
- *(auth)* Forgot to add the accesslevel 3 ([`9476dac`](https://github.com/wilsonborba/api_for_apps/commit/9476dac9d259a10502afa1da03516adae1a669cd))
- *(runtime)* Use Cloudflare production origins ([`46bee36`](https://github.com/wilsonborba/api_for_apps/commit/46bee36e9d1b9597053db6025346fb29ff92d227))
- *(runtime)* Merge Cloudflare production origin correction ([`cce2174`](https://github.com/wilsonborba/api_for_apps/commit/cce2174ffd7dce8b8f3a1124f03d77f847166313))
- *(dal)* Adopt existing error-report table ([`7c8d0b3`](https://github.com/wilsonborba/api_for_apps/commit/7c8d0b31efd84b5f0e513d7118694126cccc2871))
- *(auth)* Use Supabase server secret key ([`0668647`](https://github.com/wilsonborba/api_for_apps/commit/0668647b2d1e12d0d1344fc0746c452e1fc4548e))
- *(auth)* Preserve initiating app through OAuth ([`35c18f0`](https://github.com/wilsonborba/api_for_apps/commit/35c18f098ddaf611b1a8dccfc4e5bd6c8bb92205))
- *(auth)* Restrict exchange to approved app origins ([`b6b46ad`](https://github.com/wilsonborba/api_for_apps/commit/b6b46ad9c001d18cb151f4a2611461b180d44bed))
- Read Supabase password tokens from response root ([`6e88af5`](https://github.com/wilsonborba/api_for_apps/commit/6e88af5b9f461347ac08f40d946d03d82aeeb1b6))
- Restore Redis session lookup in app proxy ([`f5a0756`](https://github.com/wilsonborba/api_for_apps/commit/f5a075604b6723646358dc8c924843dc3f4bc93a))
- Expose Supabase password reset rejection ([`adbc8a6`](https://github.com/wilsonborba/api_for_apps/commit/adbc8a6955cf8e83ed2451c14baf682ed5b4e98a))
- Keep password reset provider detail in server logs ([`463d062`](https://github.com/wilsonborba/api_for_apps/commit/463d06281a87afe3a7f577c4040688e71b3e931b))
- *(cors)* Expand CORS allow_origin_regex for local network IPs and handle preflight headers ([`8b7c581`](https://github.com/wilsonborba/api_for_apps/commit/8b7c58165ec69e911aa0491c32f3226c036c523d))
- *(support)* Mount support router under /apps/{app}/v1/support ([`93a18f5`](https://github.com/wilsonborba/api_for_apps/commit/93a18f5b73af03bacf78cfce6db9a2048fd664b4))
- *(exchange)* Register cortex in SSO exchange allowlist ([`806870f`](https://github.com/wilsonborba/api_for_apps/commit/806870f538ad57d97844b6003c048e672cb211c3))

### 💼 Other Changes

- Initial commit ([`000f399`](https://github.com/wilsonborba/api_for_apps/commit/000f399c26cb9ec497d2014f999473f39a79aca3))
- Allow fallback to user auth when admin key invalid ([`a2d23f0`](https://github.com/wilsonborba/api_for_apps/commit/a2d23f051d8a8a58165bae45211be0b01221c47a))
- Add public proxy allowlist for unauthenticated routes ([`d3da5e8`](https://github.com/wilsonborba/api_for_apps/commit/d3da5e8868fb91b658fd279c2f7ffa69fe490492))
- Merge pull request #1 from wilsonborba/codex/implement-public-proxy-for-local-api

Allow public proxy allowlist for unauthenticated routes ([`8e98b8f`](https://github.com/wilsonborba/api_for_apps/commit/8e98b8fa94b81322216f15cd798f1ce1aa822de0))
- Merge branch 'feature/main' into codex/implement-public-proxy-for-local-api-vq4pn4 ([`a6cf99a`](https://github.com/wilsonborba/api_for_apps/commit/a6cf99a37907bbc2cae5cc1358e531a367cbb42d))
- Merge pull request #2 from wilsonborba/codex/implement-public-proxy-for-local-api-vq4pn4

Allow public proxy allowlist and fall back to user auth on invalid admin key ([`09a0839`](https://github.com/wilsonborba/api_for_apps/commit/09a0839b535566e9e2df004064481984a775f6ad))
- Centralize Supabase session exchange ([`d2515f7`](https://github.com/wilsonborba/api_for_apps/commit/d2515f70166afbd68864c3c99f27e508a77a4e9f))
- Add DAL Alembic migrations ([`d197571`](https://github.com/wilsonborba/api_for_apps/commit/d19757147989ead3f779922b11096f599046b496))
- Replace requirements with pyproject ([`5df6415`](https://github.com/wilsonborba/api_for_apps/commit/5df64159c19dae08bf0d2095ce3e898f41362274))
- Replace requirements with pyproject ([`6aa0d00`](https://github.com/wilsonborba/api_for_apps/commit/6aa0d00c4e9bd06eabc50f462ce7708bb6d1d5de))
- Adopt existing error-report table ([`d68589e`](https://github.com/wilsonborba/api_for_apps/commit/d68589eb637bae9ec175967b948cb6f9ea88742a))
- Use Supabase server secret key ([`049b938`](https://github.com/wilsonborba/api_for_apps/commit/049b93887a99926d9c2202188a666a8fe49f0f2d))
- Preserve initiating app through OAuth ([`5e0df93`](https://github.com/wilsonborba/api_for_apps/commit/5e0df93fee1a80c265a76b051d179c742c29dbd2))
- Restrict exchange to approved app origins ([`a510fc8`](https://github.com/wilsonborba/api_for_apps/commit/a510fc844e6117a6aaa2ffcb40d01f3fb452edc6))
- Read Supabase password tokens from response root ([`d29ad22`](https://github.com/wilsonborba/api_for_apps/commit/d29ad22782ef27bfbacd3b780c3e57e5f59a71fd))
- Restore Redis session lookup in app proxy ([`bc2ce55`](https://github.com/wilsonborba/api_for_apps/commit/bc2ce553268d2bcb741b4c88f397f2f236a03c9c))
- Expose Supabase password reset rejection ([`91f53fa`](https://github.com/wilsonborba/api_for_apps/commit/91f53fa809bfe8f4df9203ee8374f85d44c1dfd4))
- Keep password reset provider detail server-side ([`d1322ad`](https://github.com/wilsonborba/api_for_apps/commit/d1322add2719e04a5b46f345e0a41e27eae23dba))
- Add public Certifications waitlist gateway ([`9a4fbed`](https://github.com/wilsonborba/api_for_apps/commit/9a4fbede736698af0ec9d997a73cf7b8bd5da6fc))
- Add cross-app support ticket system ([`3fecda4`](https://github.com/wilsonborba/api_for_apps/commit/3fecda4bcec632373e840fbc9de2c9c57bec3905))
- Mount support router under /apps/{app}/v1/support ([`7a91c78`](https://github.com/wilsonborba/api_for_apps/commit/7a91c78a23cc36b6b5cffb45cbb6cc16a71ae835))
- Single role-scoped support endpoint at /apps/support/v1 ([`47ba54c`](https://github.com/wilsonborba/api_for_apps/commit/47ba54c80930c6abea2dc5e8df14bc812bbf7690))
- Merge feature/support-fsm-attachments into feature/main ([`68dfb46`](https://github.com/wilsonborba/api_for_apps/commit/68dfb4640175ab11633602adc199de70f82f56e3))
- Merge feature/support-admin-authorization into feature/main ([`5e63da5`](https://github.com/wilsonborba/api_for_apps/commit/5e63da5390893207b87a01fe5001068d48a445e5))
- Feature/19-cortex-proxy-attestation into feature/main ([`521cd74`](https://github.com/wilsonborba/api_for_apps/commit/521cd746945b8a2093dfde9e778ccc1242eedaa9))
- Fix/21-register-cortex-exchange-app into feature/main ([`6033a83`](https://github.com/wilsonborba/api_for_apps/commit/6033a83c068f0a02fc3d4b85db19448d85a29b09))
- Merge branch 'feature/main' into development ([`0c8b242`](https://github.com/wilsonborba/api_for_apps/commit/0c8b2422448845049553cabedc1ca8a2c371e2da))

### 🚜 Refactor

- *(auth)* Distinguish app context from exchange token ([`2d8d88e`](https://github.com/wilsonborba/api_for_apps/commit/2d8d88ecb3c0c4cfd56319124193fd8005d7311c))
- *(auth)* Centralize Supabase session exchange ([`2cbbd00`](https://github.com/wilsonborba/api_for_apps/commit/2cbbd0001f4e28c509103e6a23849aff5bc926c9))
- *(support)* Single role-scoped endpoint at /apps/support/v1 ([`ba07d5b`](https://github.com/wilsonborba/api_for_apps/commit/ba07d5bbdebbd07210853196742814651bb20d2e))

### ⚙️ Miscellaneous Tasks

- *(env)* Created initial env struct for api/middleware ([`6af55b8`](https://github.com/wilsonborba/api_for_apps/commit/6af55b815faed0d91278e89e664454ad97489fe5))
- *(env)* Created initial route for testing ([`09ac46e`](https://github.com/wilsonborba/api_for_apps/commit/09ac46e80b9f2207b883fbb1f764b04c7785aba1))
- *(docs)* Missed commit the changelog file ([`e5a1052`](https://github.com/wilsonborba/api_for_apps/commit/e5a1052f5179e2781b16ba226b70ea15767e6a52))
- *(release)* Adjusted the bash run application for prod and dev ([`91a9b4f`](https://github.com/wilsonborba/api_for_apps/commit/91a9b4f3b7da55750364d0b00ff2b617db4dcd97))
- *(release)* Created a install bash script for systemctl service ([`abb4f38`](https://github.com/wilsonborba/api_for_apps/commit/abb4f38a250c1cd43265fa2a73b56e33277c9499))
- *(runtime)* Configure gateway endpoints ([`9333df6`](https://github.com/wilsonborba/api_for_apps/commit/9333df625604befb9f9c513b426cba768b4d8380))
- *(runtime)* Merge gateway endpoint configuration ([`33c0eea`](https://github.com/wilsonborba/api_for_apps/commit/33c0eea0a24855cd78389b3c8ef11aac31ce9912))
<!-- generated by git-cliff -->
