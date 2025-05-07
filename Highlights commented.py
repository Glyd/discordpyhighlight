import asyncio
import discord
from discord.ext import commands
from cogs.utils.HighlightUtils import create_embed_from_ids, send_attachments
from Laurelin import logMessage, config_manager, PIN_EMOTE, ACTUAL_PIN_EMOTE_LMAO

## Hi! I'm sola, I wrote a few explainer comments to help, feel free to tag me if you have any questions :-) 
## @s.la on discord

## Quick notes:
## config_manager is simply a class to provide access to a json file. See config-example.json for what's needed.
### PIN_EMOTE = '⭐'
### ACTUAL_PIN_EMOTE_LMAO = '📌'
### REACT_THRESHOLD is the threshold for any reactions. 
### USER_STAR_REACT_THRESHOLD is the threshold for non-moderators using the highlight reaction (PIN_EMOTE / ⭐) to provide a community force-pin option.
### Moderators (or specified roles) will force-pin with this same reaction.

## on_reaction_add and on_raw_reaction_add (cached/uncached respectively) process each reaction as they come in.
## They trigger highlight_message_in_channel when the threshold is met and no excluding conditions are present.
## Exclusion functionality was put in place to prevent highlights of overly personal/venty content. This may not be necessary,
## and could easily be removed to optimise.

class Highlights(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    # Optional feature that reposts a message using the highlight code. Useful for testing. 
    @commands.command()
    async def dontquoteme(self, ctx):
        if ctx.message.reference is not None:
            try:
                replied_message = ctx.message.reference.cached_message
                #if not cached, retrieve message
                if replied_message is None:
                    replied_message = await ctx.fetch_message(ctx.message.reference.message_id)
                    
                channel = ctx.channel

                createdEmbed = await create_embed_from_ids(self.bot, replied_message.id, replied_message.channel.id, False, emoji="")

                await channel.send(embed=createdEmbed)
            except Exception as e:
                await ctx.send(f'Uh oh {e}')
        else:
            await ctx.send('Uh oh You need to reply')

    # Command to force highlight a message.
    @commands.has_permissions(ban_members=True)
    @commands.command()
    async def highlight(self, ctx):
        if ctx.message.reference is not None:
            try:
                replied_message = ctx.message.reference.cached_message
                channel = ctx.channel
                
                #if not cached, retrieve message
                if replied_message is None:
                    replied_message = await ctx.fetch_message(ctx.message.reference.message_id)
                    
                await self.highlight_message_in_channel(replied_message)
            except Exception as e:
                await ctx.send(f'Uh oh {e}')
        else:
            await ctx.send('Uh oh You need to reply')

    ## MAIN FUNCTION
    ## highlight_message_in_channel fetches message content (text, embeds, attachments) and posts them as a highlight after checking
    ## for excluded channels or words.
    async def highlight_message_in_channel(self, message):
        shouldPostMessage = True
        await logMessage("Highlight message was called")
        
        ## OPTIONAL: Prevent highlights posting from certain channels or if they contain certain words. 
        ## Both are simply JSON arrays in a config file. See provided config-example.json

        if message.channel.id in config_manager.get("EXCLUDED_CHANNEL_IDS"):
            await logMessage("Channel excluded")
            shouldPostMessage = False

        for reaction in message.reactions:
            if reaction.emoji == PIN_EMOTE and reaction.me:
                shouldPostMessage = False

        if any(word.lower() in message.clean_content.lower() for word in config_manager.get("EXCLUSION_WORDS")):
            shouldPostMessage = False
            
        ## END OPTIONAL
        
        ## Loads message contents. Sends some attachments as a separate message due to embed limitations e.g. multiple images
        ## Links will not embed - posting them separately was removed after trying it. You may want to re-implement that
        if message.author != self.bot.user and shouldPostMessage:
            createdEmbed = None
            attachments = None
            
            if len(message.attachments) > 1:
                createdEmbed, attachments = await create_embed_from_ids(self.bot, message.id, message.channel.id, False)
            else:
                createdEmbed = await create_embed_from_ids(self.bot, message.id, message.channel.id, False)

            if shouldPostMessage and message.attachments:
                if len(message.attachments) > 1:
                    try:
                        channel = self.bot.get_channel(config_manager.get("CHANNEL_ID_TO_POST_POPULAR_MESSAGES"))
                        await channel.send(embed=createdEmbed)
                        await self.send_attachments(channel, attachments)
                    except Exception as e:
                        await logMessage(f"Error sending multi-attachment highlight: {e}")

            if shouldPostMessage and createdEmbed:
                channel = self.bot.get_channel(config_manager.get("CHANNEL_ID_TO_POST_POPULAR_MESSAGES"))
                try:
                    await channel.send(embed=createdEmbed)
                except Exception as e:
                    await logMessage(f"Error sending pin message: {e}")
            else:
                channel = self.bot.get_channel(config_manager.get("CHANNEL_ID_TO_POST_POPULAR_MESSAGES"))
                try:
                    await channel.send(embed=createdEmbed)
                except Exception as e:
                    await logMessage(f"Error sending link message: {e}")

            await message.add_reaction(PIN_EMOTE)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        message_id = reaction.message.id

        # This allows users to react with an ❌ to delete their own highlights. Also see: ask_confirmation
        if reaction.message.channel.id == config_manager.get("CHANNEL_ID_TO_POST_POPULAR_MESSAGES") and reaction.emoji == '❌':
            message = reaction.message

            author_name = message.embeds[0].author.name

            # Check if the user who reacted has the same name as the author of the highlighted message
            if user.name == author_name:
                # Ask for confirmation and proceed accordingly
                confirmation = await self.ask_confirmation(user, message)

                if confirmation:
                    await message.delete()
                else:
                    await message.remove_reaction('❌', user)
                    
        # Checking each react as it comes in to see if that react reached the highlight threshold,
        # or if it was a moderator using the defined (PIN_EMOTE) force-pin react.
        if reaction.message.channel.id not in config_manager.get("EXCLUDED_CHANNEL_IDS") and reaction.message.guild.id == config_manager.get("GUILD_ID"):
            containsExcludedWord = False
            didModForcePin = False
            didBotPin = reaction.me
            hitThreshold = False
            message = reaction.message

            try:
                # OPTIONAL: Check for excluded words
                if any(word.lower() in message.clean_content.lower() for word in config_manager.get("EXCLUSION_WORDS")):
                    containsExcludedWord = True
                    await logMessage(f"Excluded word found in message: {message.clean_content}, no highlight")

                if not containsExcludedWord:
                    # Handle the pin emote - check if mod, pin if so. Stop ALL processing if the bot has already pinned it (bot adds it's own star).
                    # This is hard to detect and double posting can happen due to async. More attempts at prevention == more problems IME
                    if reaction.emoji == PIN_EMOTE:
                        modRole = discord.utils.get(message.guild.roles, name="Moderators")
                        legacyRole = discord.utils.get(message.guild.roles, name="Legacy")

                        if modRole in user.roles or legacyRole in user.roles:
                            didModForcePin = True
                            await logMessage(f"Moderator created highlight - {user.name} - jump url: {message.jump_url}")
                        elif user.id == self.bot.user.id:
                            didBotPin = True
                            didModForcePin = False
                        elif reaction.count >= config_manager.get("USER_STAR_REACT_THRESHOLD"):
                            hitThreshold = True
                            await logMessage(f"Threshold hit 1 - message jump url: {message.jump_url}")
                    elif not didBotPin and not didModForcePin:
                        if hasattr(reaction.emoji, 'name'):
                            # Check if the react itself is excluded - e.g. hugging or other reacts typically used on venting / personal things
                            if not reaction.emoji.name in config_manager.get("HL_EXCLUDED_REACTS"):
                                if reaction.count >= config_manager.get("REACT_THRESHOLD"):
                                    hitThreshold = True
                                    await logMessage(f"Threshold hit 2 - message jump url: {message.jump_url}")
                            else:
                                await logMessage("Reaction blacklisted (custom emoji), no highlight")
                        else:
                            # For Unicode emojis (without name)
                            emoji_str = str(reaction.emoji)

                            #Specific check for unicode hug
                            if emoji_str in "🫂":
                                await logMessage(f"Reaction blacklisted (Unicode emoji), no highlight")
                            else:
                                if reaction.count >= config_manager.get("REACT_THRESHOLD"):
                                    hitThreshold = True # All checks passed and threshold is met at this point

                # Perform the highlight if conditions are met
                if not didBotPin and not containsExcludedWord:
                    if didModForcePin or hitThreshold:
                        await self.highlight_message_in_channel(message)
                else:
                    await logMessage("Message already pinned")

            except Exception as e:
                await logMessage(f"Error highlighting cached message: {e}")

    # The same as on_reaction_add, but for reactions on uncached message. This means it has to fetch the message details
    # which have some differences to cached ones. The duplication may be avoidable but IMO less maintainable and readable. 
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        user = guild.get_member(payload.user_id)
        reaction = discord.utils.get(message.reactions, emoji=payload.emoji.name)

        if channel.id == config_manager.get("CHANNEL_ID_TO_POST_POPULAR_MESSAGES") and payload.emoji.name == '❌':
            author_name = message.embeds[0].author.name
            if user.name == author_name:
                confirmation = await self.ask_confirmation(user, message)
                if confirmation:
                    await message.delete()
                else:
                    await message.remove_reaction('❌', user)

        if channel.id not in config_manager.get("EXCLUDED_CHANNEL_IDS") and guild.id == config_manager.get("GUILD_ID"):
            containsExcludedWord = False
            didModForcePin = False
            didBotPin = payload.user_id == self.bot.user.id
            hitThreshold = False

            try:
                if any(word.lower() in message.clean_content.lower() for word in config_manager.get("EXCLUSION_WORDS")):
                    containsExcludedWord = True
                    await logMessage(f"Excluded word found in message: {message.clean_content}, no highlight")

                if not containsExcludedWord:
                    if payload.emoji.name == ACTUAL_PIN_EMOTE_LMAO: #Note: Different pin emote for uncached messages.
                        # These roles are allowed to force pin.
                        modRole = discord.utils.get(guild.roles, name="Moderators")
                        legacyRole = discord.utils.get(guild.roles, name="Legacy")

                        if modRole in user.roles or legacyRole in user.roles:
                            didModForcePin = True
                            await logMessage(f"Moderator created highlight - {user.name} - jump url: {message.jump_url}")
                        elif reaction and reaction.count >= config_manager.get("USER_STAR_REACT_THRESHOLD"):
                            hitThreshold = True
                    elif not didBotPin and not didModForcePin:
                        if hasattr(payload.emoji, 'name'):
                            if not payload.emoji.name in config_manager.get("HL_EXCLUDED_REACTS"):
                                if reaction and reaction.count >= config_manager.get("REACT_THRESHOLD"):
                                    hitThreshold = True
                            else:
                                await logMessage("Reaction blacklisted (custom emoji), no highlight")
                        else:
                            # OPTIONAL: Exclude hug emoji 
                            emoji_str = str(payload.emoji)

                            if emoji_str in "🫂":
                                await logMessage(f"Reaction blacklisted (Unicode emoji), no highlight")
                            else:
                                if reaction and reaction.count >= config_manager.get("REACT_THRESHOLD"):
                                    hitThreshold = True

                if not didBotPin and not containsExcludedWord:
                    if didModForcePin or hitThreshold:
                        await self.highlight_message_in_channel(message)
                else:
                    await logMessage("Message already pinned")

            except Exception as e:
                await logMessage(f"Error highlighting raw message: {e}")

    # Deals with deleting a users highlight when requested.
    async def ask_confirmation(self, user, message):
        confirmation_message = await message.channel.send(
            f"{user.mention}, do you want to delete this highlight?\nReact with ✅ to confirm, ❌ to cancel. (15 seconds)\nPlease contact a moderator to delete if this fails.",
            delete_after=15.0,
        )

        await confirmation_message.add_reaction('✅')
        await confirmation_message.add_reaction('❌')

        def check(reaction, reacting_user):
            return reacting_user == user and str(reaction.emoji) in ['✅', '❌']

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=15.0, check=check)
            if str(reaction.emoji) == '✅':
                await message.delete()
            else:
                await message.remove_reaction('❌', user)
        except asyncio.TimeoutError:
            await message.remove_reaction('❌', user)
        finally:
            await confirmation_message.delete()
    
    # Sends attachments as a separate message. This is used to post the contents of a message with multiple attachments.
    async def send_attachments(self, channel, attachments):
        for attachment in attachments:
            await channel.send(file=await attachment.to_file())

# discord.py setup, not needed if yoinking
async def setup(bot):
    await bot.add_cog(Highlights(bot))