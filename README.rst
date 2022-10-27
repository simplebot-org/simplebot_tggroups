Telegram Groups Bridge
======================

.. image:: https://img.shields.io/pypi/v/simplebot_tggroups.svg
   :target: https://pypi.org/project/simplebot_tggroups

.. image:: https://img.shields.io/pypi/pyversions/simplebot_tggroups.svg
   :target: https://pypi.org/project/simplebot_tggroups

.. image:: https://pepy.tech/badge/simplebot_tggroups
   :target: https://pepy.tech/project/simplebot_tggroups

.. image:: https://img.shields.io/pypi/l/simplebot_tggroups.svg
   :target: https://pypi.org/project/simplebot_tggroups

.. image:: https://github.com/simplebot-org/simplebot_tggroups/actions/workflows/python-ci.yml/badge.svg
   :target: https://github.com/simplebot-org/simplebot_tggroups/actions/workflows/python-ci.yml

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black

A `SimpleBot`_ plugin that allows to bridge Telegram and Delta Chat groups.

    For channel subscriptions use: https://github.com/simplebot-org/simplebot_tgchan

Installation
------------

To install run::

  pip install simplebot-tggroups

Configuration
-------------

See https://github.com/simplebot-org/simplebot to know how to configure the bot with an e-mail account.

Before you start using the bot, you need to get your own API ID and hash, go to https://my.telegram.org,
you also need a bot token, got to [@BotFather](https://t.me/botfather) on Telegram and create a bot,
then to set API ID, API hash and bot token, execute::

    simplebot -a bot@example.com telegram

After configuration you can start the bot::

    simplebot -a bot@example.com serve

Then you can start bridging Telegram and Delta Chat groups, send ``/help`` to the bot in Delta Chat for
more info.

To bridge a Telegram group to a Delta Chat group:

1. Add the bot in Telegram to your group.
2. Send ``/id`` command in the Telegram group, copy the ID returned by the bot.
3. Add the bot in Delta Chat to your group.
4. Send ``/bridge 1234`` where ``1234`` is the group ID obtained in the Telegram group.
5. Then all messages sent in both groups will be relayed to the other side.

Tweaking Default Configuration
------------------------------

You can tweak the maximum size (in bytes) of attachments the bot will bridge::

    simplebot -a bot@example.com telegram --max-size 5242880

By default the bot will download attachments of up to 5MB.


.. _SimpleBot: https://github.com/simplebot-org/simplebot
