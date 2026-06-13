This project is to gain experience with the new google health api for registering fitbit users so they can share data with my server.

Prior work I have done was with the legacy fitbit api.

linked code is in fitbitreg and garmin_django

I imagine this as a two step process.

1. Setup up the oauth2 mechanism for users and store their tokens in the database.

2. setup subscriptions to a users' data

3. Need a UI that allows a researcher to create a study and enter subjects that then allows them to register with a code.

4. UI also supports review of collected data and the ability to download it.

5. Consider react front end, fastapi backend with webhooks for data subscriptions, mariadb relational database

6. Use google auth for user 2FA authentication - only allow access for users already entered.  User has to be connected to a study.

7. Admin user can create studies and make allow a user to be an admin for that study so they can add users and give them permissions such as to add subjects and download data.

8. garmin also supported see garminrec
Question is it better to separate the garmin and fitbit oauth applications since somewhat different?

9. UI similar to https://github.com/kelvinlim/chan_cras  Use UMN branding found here: https://umarcomm.umn.edu/brand The code is in the linked chan_cras

10. screen shot of detail of selection of study and subjects for reference style/cras_study_screenshot.jpeg 


