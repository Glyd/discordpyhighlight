import random
import discord
from cogs.utils.ConfigManager import config_manager

PRIDE_COLORS = [0xE40303, 0xFF8C00, 0xFFED00, 0x008026, 0x24408E, 0x732982, 0x000000, 0x654321, 0xADD8E6, 0xFFB6C1, 0xFFFFFF]
LAST_PRIDE_COLOR = -1

async def create_embed_from_ids(bot, message_id, channel_id, use_random_color=True, emoji="⭐"):
    global LAST_PRIDE_COLOR
    global PRIDE_COLORS
    try:
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        
        # Initialize embed
        author = message.author
        content = message.clean_content
        
        colorToUse = None
        colorToUse = random.choice(PRIDE_COLORS) if use_random_color else PRIDE_COLORS[LAST_PRIDE_COLOR + 1]
        
        if not use_random_color:
            LAST_PRIDE_COLOR += 1
            if LAST_PRIDE_COLOR >= len(PRIDE_COLORS) - 1:
                LAST_PRIDE_COLOR = -1
            
        createdEmbed = discord.Embed(title=f"{emoji}", color=colorToUse)
        
        if message.reference and message.reference.message_id:
            referenced_message = await channel.fetch_message(message.reference.message_id)
            referenced_author = referenced_message.author
            referenced_content = referenced_message.clean_content
            
            # Add referenced message information to the embed
            if (len(referenced_message.clean_content) > 0):
                createdEmbed.add_field(
                    name=f"",
                    value=f"-# **{referenced_author}** said:\n-# {referenced_content}",
                    inline=False
                )
            else:
                createdEmbed.add_field(
                    name=f"",
                    value=f"-# **In reply to {referenced_author}**",
                    inline=False
                )
        
        createdEmbed.set_author(name=author.name, icon_url=author.display_avatar.url)
        createdEmbed.add_field(name="", value=content or "\u200b", inline=False)
        createdEmbed.add_field(name="", value=f'[[Jump to message]]({message.jump_url})', inline=False)
        
        # Handle attachments
        if message.attachments:
            if len(message.attachments) > 1:
                return createdEmbed, message.attachments  # Handle multi-attachments separately
            else:
                attachment = message.attachments[0]
                if attachment.content_type and attachment.content_type.startswith("image"):
                    createdEmbed.set_image(url=attachment.url)
                    
        # Handle existing embeds in the message
        if message.embeds:
            embed = message.embeds[0]
            if embed.type == "image":
                createdEmbed.set_image(url=embed.url)
        
        return createdEmbed  # No issues, return the embed
    
    except Exception as e:
        await bot.get_channel(config_manager.get("CHANNEL_ID_TO_POST_LOGS")).send(f"Error creating embed from URL: {e}")
        return None
    
async def send_attachments(channel, attachments):
    attachment_text = '\n'.join(f'[{index}]({attachment.url})' for index, attachment in enumerate(attachments, start=1))
    await channel.send('', files=[await attachment.to_file() for attachment in attachments])