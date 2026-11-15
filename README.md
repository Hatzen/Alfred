# Alfred

Program that can run as a daemon and is a AI Assist like Alexa but even better and more features with full privacy focus.  
Mainfeatures.
maybe we can have a look at already existing repos and utilitize these, but we want all cool features over here

- Should run locally and utilitize a configurable api
- Should support localais apis for tts, sst, vad and chat api
- Filter for configurable "Names" like "Hey Alexa", "Hey Google", "Hey Alfred" which is needed to do heavy tasks
- we should focus a little on performance so we dont use 100% cpu just to detect commands 
- should be able to "learn". which means persisting memories and change personality etc. and like this we should be able to create Alexa like Skills
- Should be able to communicate with REST, APIs and learn how to use them e.g. a robot like FancyTanky or Paperless for Informations or just search the internet for informations like wikipedia or google
- sensitiv informations need a dynamic passphrase which is configurable as well. e.g. configured is the word "Nilpferd" additionally the number for this weekday is needed e.g. Monday is one so NilpferdOne Nilpfer1 would be the password
   - sensitiv informations can be defined but will be checked as well, e.g. looking for pornography or personal informations like taxnumber or anything that sounds harmful needs this password
- very very cool would be if we can say "stop" or "forget it" and the ai instantly drops the answer.
- espacially when it is talking we should be able to say "stop" or "forget it" and then stops the output.
- Microphone and Output device should be configured espacially we should have an option for smart choice, so it just uses the mic which is activley giving input and the output device that seems to be working best, e.g. by soundcheck and sending a specific
- we should have cool beep sounds or similar to get feedback that it is doing something espacially when generating etc is
- can we integrate this usefully with local running hermes?
- we should support different languages, mainly focussing on German/ Deutsch
