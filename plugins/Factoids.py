#!/usr/bin/env python

###
# Copyright (c) 2002, Jeremiah Fincher
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

"""
Handles "factoids," little tidbits of information held in a database and
available on demand via several commands.
"""

from baseplugin import *

import time
import os.path

import sqlite

import conf
import ircdb
import privmsgs
import callbacks

class Factoids(ChannelDBHandler, callbacks.Privmsg):
    def __init__(self):
        ChannelDBHandler.__init__(self)
        callbacks.Privmsg.__init__(self)

    def makeDb(self, filename):
        if os.path.exists(filename):
            return sqlite.connect(filename)
        db = sqlite.connect(filename)
        cursor = db.cursor()
        cursor.execute("""CREATE TABLE keys (
                          id INTEGER PRIMARY KEY,
                          key TEXT UNIQUE ON CONFLICT IGNORE,
                          locked BOOLEAN
                          )""")
        cursor.execute("""CREATE TABLE factoids (
                          id INTEGER PRIMARY KEY,
                          key_id INTEGER,
                          added_by TEXT,
                          added_at TIMESTAMP,
                          fact TEXT
                          )""")
        cursor.execute("""CREATE TRIGGER remove_factoids
                          BEFORE DELETE ON keys
                          BEGIN
                            DELETE FROM factoids WHERE key_id = old.id;
                          END
                       """)
        db.commit()
        return db

    def learn(self, irc, msg, args):
        """[<channel>] <key> as <value>

        Associates <key> with <value>.  <channel> is only necessary if the
        message isn't sent on the channel itself.
        """
        channel = privmsgs.getChannel(msg, args)
        try:
            i = args.index('as')
        except ValueError:
            raise callbacks.ArgumentError
        args.pop(i)
        key = ' '.join(args[:i])
        factoid = ' '.join(args[i:])
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT id, locked FROM keys WHERE key=%s""", key)
        if cursor.rowcount == 0:
            cursor.execute("""INSERT INTO keys VALUES (NULL, %s, 0)""", key)
            db.commit()
            cursor.execute("""SELECT id, locked FROM keys WHERE key=%s""", key)
        (id, locked) = map(int, cursor.fetchone())
        capability = ircdb.makeChannelCapability(channel, 'factoids')
        if not locked:
            if not ircdb.checkCapability(msg.prefix, capability):
                irc.error(msg, conf.replyNoCapability % capability)
                return
            if ircdb.users.hasUser(msg.prefix):
                name = ircdb.users.getUserName(msg.prefix)
            else:
                name = msg.nick
            cursor.execute("""INSERT INTO factoids VALUES
                              (NULL, %s, %s, %s, %s)""",
                           id, name, int(time.time()), factoid)
            db.commit()
            irc.reply(msg, conf.replySuccess)
        else:
            irc.error(msg, 'That factoid is locked.')

    def whatis(self, irc, msg, args):
        """[<channel>] <key> [<number>]

        Looks up the value of <key> in the factoid database.  If given a
        number, will return only that exact factoid.  <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        channel = privmsgs.getChannel(msg, args)
        key = privmsgs.getArgs(args)
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT factoids.fact FROM factoids, keys WHERE
                          keys.key=%s AND factoids.key_id=keys.id
                          ORDER BY factoids.id
                          LIMIT 20""", key)
        if cursor.rowcount == 0:
            irc.error(msg, 'No factoid matches that key.')
        else:
            counter = 0
            factoids = []
            for result in cursor.fetchall():
                factoids.append('(#%s) %s' % (counter, result[0]))
                counter += 1
            totalResults = len(factoids)
            if ircutils.shrinkList(factoids, ', or ', 400):
                s = '%s could be %s. (%s results shown out of %s)' % \
                    (key, ', or '.join(factoids), counter-1, totalResults)
            else:
                s = '%s could be %s.' % (key, ', or '.join(factoids))
            irc.reply(msg, s)

    def lock(self, irc, msg, args):
        """[<channel>] <key>

        Locks the factoid(s) associated with <key> so that they cannot be
        removed or added to.  <channel> is only necessary if the message isn't
        sent in the channel itself.
        """
        channel = privmsgs.getChannel(msg, args)
        key = privmsgs.getArgs(args)
        db = self.getDb(channel)
        capability = ircdb.makeChannelCapability(channel, 'factoids')
        if ircdb.checkCapability(msg.prefix, capability):
            cursor = db.cursor()
            cursor.execute("""UPDATE keys SET locked = 1 WHERE key=%s""", key)
            db.commit()
            irc.reply(msg, conf.replySuccess)
        else:
            irc.error(msg, conf.replyNoCapability % capability)

    def unlock(self, irc, msg, args):
        """[<channel>] <key>

        Unlocks the factoid(s) associated with <key> so that they can be
        removed or added to.  <channel> is only necessary if the message isn't
        sent in the channel itself.
        """
        channel = privmsgs.getChannel(msg, args)
        key = privmsgs.getArgs(args)
        db = self.getDb(channel)
        capability = ircdb.makeChannelCapability(channel, 'factoids')
        if ircdb.checkCapability(msg.prefix, capability):
            cursor = db.cursor()
            cursor.execute("""UPDATE keys SET locked = 0 WHERE key=%s""", key)
            db.commit()
            irc.reply(msg, conf.replySuccess)
        else:
            irc.error(msg, conf.replyNoCapability % capability)

    def unlearn(self, irc, msg, args):
        """[<channel>] <key> [<number>]

        Removes the factoid <key> from the factoids database.  If there are
        more than one factoid with such a key, a number is necessary to
        determine which one should be removed.  <channel> is only necessary if
        the message isn't sent in the channel itself.
        """
        channel = privmsgs.getChannel(msg, args)
        if args[-1].isdigit:
            number = int(args.pop())
        else:
            number = None
        key = privmsgs.getArgs(args)
        db = self.getDb(channel)
        capability = ircdb.makeChannelCapability(channel, 'factoids')
        if ircdb.checkCapability(msg.prefix, capability):
            cursor = db.cursor()
            cursor.execute("""SELECT keys.id, factoids.id
                              FROM keys, factoids
                              WHERE key=%s AND
                                    factoids.key_id=keys.id""", key)
            if cursor.rowcount == 0:
                irc.error(msg, 'There is no such factoid.')
            elif cursor.rowcount == 1:
                (id, _) = cursor.fetchone()
                cursor.execute("""DELETE FROM factoids WHERE key_id=%s""", id)
                cursor.execute("""DELETE FROM keys WHERE key=%s""", key)
                db.commit()
                irc.reply(msg, conf.replySuccess)
            else:
                if number is not None:
                    results = cursor.fetchall()
                    try:
                        (_, id) = results[number]
                    except IndexError:
                        irc.error(msg, 'Invalid factoid number.')
                        return
                    cursor.execute("DELETE FROM factoids WHERE id=%s", id)
                    db.commit()
                    irc.reply(msg, conf.replySuccess)
                else:
                    irc.error(msg, '%s factoids have that key.  ' \
                                   'Please specify which one to remove.' % \
                                   cursor.rowcount)
        else:
            irc.error(msg, conf.replyNoCapability % capability)

    def randomfactoid(self, irc, msg, args):
        """[<channel>]

        Returns a random factoid from the database for <channel>.  <channel>
        is only necessary if the message isn't sent in the channel itself.
        """
        channel = privmsgs.getChannel(msg, args)
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT fact, key_id FROM factoids
                          ORDER BY random()
                          LIMIT 1""")
        if cursor.rowcount != 0:
            (factoid, keyId) = cursor.fetchone()
            cursor.execute("""SELECT key FROM keys WHERE id=%s""", keyId)
            key = cursor.fetchone()[0]
            irc.reply(msg, '%s: %s' % (key, factoid))
        else:
            irc.error(msg, 'I couldn\'t find a factoid.')

    def factoidinfo(self, irc, msg, args):
        """[<channel>] <key>

        Gives information about the factoid(s) associated with <key>.
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        channel = privmsgs.getChannel(msg, args)
        key = privmsgs.getArgs(args)
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT id, locked FROM keys WHERE key=%s""", key)
        if cursor.rowcount == 0:
            irc.error(msg, 'No factoid matches that key.')
            return
        (id, locked) = map(int, cursor.fetchone())
        cursor.execute("""SELECT  added_by, added_at FROM factoids
                          WHERE key_id=%s
                          ORDER BY id""", id)
        factoids = cursor.fetchall()
        L = []
        counter = 0
        for (added_by, added_at) in factoids:
            added_at = time.strftime(conf.humanTimestampFormat,
                                     time.localtime(int(added_at)))
            L.append('#%s was added by %s at %s' % (counter,added_by,added_at))
            counter += 1
        factoids = '; '.join(L)
        s = 'Key %r is %s and has %s factoids associated with it: %s' % \
            (key, locked and 'locked' or 'not locked', counter, factoids)
        irc.reply(msg, s)



Class = Factoids
# vim:set shiftwidth=4 tabstop=8 expandtab textwidth=78:
