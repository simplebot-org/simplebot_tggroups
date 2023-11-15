# Changelog

## [v0.3.0]

### Changed

- don't send ID in private chats on Telegram

### Fixed

- check if `event.message.sender` is `None` to avoid `AttributeError`.

## [v0.2.0]

### Added

- added support for message replies/quotes
- register bot's supported commands in Telegram for better usability

### Changed

- improve debugging
- truncate too long nicknames when relaying messages to telegram
- convert `.acc` voice messages to mp3

### Fixed

- ignore messages from self
- remove bridge if the Telegram chat ID is invalid or the bot was removed from the Telegram chat

## v0.1.0

- initial release


[Unreleased]: https://github.com/simplebot-org/simplebot_tggroups/compare/v0.3.0...HEAD
[v0.3.0]: https://github.com/simplebot-org/simplebot_tggroups/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/simplebot-org/simplebot_tggroups/compare/v0.1.0...v0.2.0
