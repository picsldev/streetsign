# -*- coding: utf-8 -*-
#     StreetSign Digital Signage Project
#     (C) Copyright 2013 Daniel Fairhead
#
#    StreetSign is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    StreetSign is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with StreetSign.  If not, see <http://www.gnu.org/licenses/>.
#
#    ---------------------------------

""" 
    streetsign_server.views.feeds_and_posts
    ---------------------------------------
    Views for editing feeds and posts.

"""



from flask import render_template, url_for, request, redirect, \
                  flash, json 
import streetsign_server.user_session as user_session
import streetsign_server.post_types as post_types
import peewee
from datetime import datetime, timedelta
from streetsign_server.views.utils import PleaseRedirect

from streetsign_server.logic.feeds_and_posts import try_to_set_feed, \
                                      if_i_cant_write_then_i_quit, \
                                      can_user_write_and_publish, \
                                      post_form_intake

from streetsign_server import app
from streetsign_server.models import User, Group, Feed, Post, ExternalSource, \
                                     by_id

import streetsign_server.external_source_types as external_source_types

####################################################################
# Feeds & Posts:

@app.route('/feeds', methods=['GET','POST'])
def feeds():
    if request.method == 'POST':
        if not user_session.is_admin():
            flash('Only Admins can do this!')
            return redirect(url_for('feeds'))

        action = request.form.get('action','create')

        if action == 'create':
            if not request.form.get('title','').strip():
                flash("I'm not making you an un-named feed!")
                return redirect(url_for('feeds'))
            Feed(name=request.form.get('title','blank').strip()).save()

    try:
        user = user_session.get_user()
    except user_session.NotLoggedIn as e:
        user = User()

    return render_template('feeds.html',
                           feeds=Feed.select(),
                           user=user,
                           external_sources=ExternalSource.select(),
                           source_types=external_source_types.types())

@app.route('/feeds/<int:feedid>', methods=['GET','POST'])
def feedpage(feedid):
    try:
        feed = Feed.get(id=feedid)
        user = user_session.get_user()
    except user_session.NotLoggedIn as e:
        user = User()
    except:
        flash('invalid feed id! (' + str(feedid) + ')')
        return redirect(url_for('feeds'))

    if request.method == 'POST':
        if not user_session.logged_in():
            flash("You're not logged in!")
            return redirect(url_for('feeds'))

        if not user.is_admin:
            flash('Sorry! Only Admins can change these details.')
            return redirect(request.referrer)

        action = request.form.get('action','none')

        if action == 'edit':
            feed.name = request.form.get('title', feed.name).strip()
            inlist = request.form.getlist

            feed.set_authors(by_id(User, inlist('authors')))
            feed.set_publishers(by_id(User, inlist('publishers')))
            feed.set_author_groups(by_id(Group, inlist('author_groups')))
            feed.set_publisher_groups(by_id(Group, inlist('publisher_groups')))

            feed.save()
            flash('Saved')
        elif action == 'delete':
            feed.delete_instance(True, True) # cascade/recursive delete.
            flash('Deleted')
            return redirect(url_for('feeds'))

    return render_template('feed.html',
                     feed=feed,
                     user=user,
                     allusers=User.select(),
                     allgroups=Group.select()
                )



##########################################
# Posts:


@app.route('/posts')
def posts():
    ''' (HTML) list of ALL posts. (also deletes broken posts, if error) '''

    try:
        return render_template('posts.html', posts=Post.select())
    except Feed.DoesNotExist as e:
        # Ah. Database inconsistancy! Not good, lah.
        ps = Post.raw('select post.id from post left join feed on feed.id = post.feed_id where feed.id is null;')
        for p in ps:
            p.delete_instance()
        flash('Cleaned up old posts...')
        return render_template('posts.html', posts=Post.select())

@app.route('/posts/new', methods=['GET','POST'])
def post_new():
    ''' create a new post! '''

    if not user_session.logged_in():
        flash("You're not logged in!")
        return redirect(url_for('index'))

    user = user_session.get_user()

    if request.method == 'GET':
        # send a blank form for the user:

        feed = int(request.args.get('initial_feed', 1))
        return render_template('postnew.html',
                current_feed=feed,
                post=Post(),
                feedlist = user.writeable_feeds(),
                can_write = True,
                post_types=post_types.types())

    else: # POST. new post!
        post_type = request.form.get('post_type')
        try:
            editor = post_types.load(post_type)
        except:
            flash('Sorry! invalid post type.')
            return redirect(request.referrer)

        post = Post(type=post_type, author=user)

        try:
            post.feed = try_to_set_feed(post, request.form, user)

            if_i_cant_write_then_i_quit(post, user)

            post_form_intake(post, request.form, editor)

        except PleaseRedirect as e:
            flash (str(e.msg))
            return(redirect(e.url if e.url else request.url))

        post.save()
        flash('Saved!')

        return redirect(url_for('feedpage', feedid=post.feed.id))

@app.route('/posts/<int:postid>', methods=['GET','POST'])
def postpage(postid):
    ''' Edit a post. '''

    if not user_session.logged_in():
        flash("You're not logged in!")
        return redirect(url_for('posts'))

    try:
        post = Post.get(Post.id==postid)
        editor = post_types.load(post.type)
        user = user_session.get_user()

    except Post.DoesNotExist:
        flash('Sorry! Post id:{0} not found!'.format(postid))
        return(redirect(url_for('posts')))

    if request.method == 'POST':
        try:
            # if the user is allowed to set the feed to what they've
            # requested, then do it.

            post.feed = try_to_set_feed(post, request.form, user)

            # check for write permission, and if the post is
            # already published, publish permission.

            if_i_cant_write_then_i_quit(post, user)

        except PleaseRedirect as e:
            flash(str(e.msg))
            redirect(e.url)

        # if it's a publish or delete request, handle that instead:
        DO = request.form.get('action','edit')
        if DO == 'delete':
            post.delete_instance()
            flash('Deleted')
            return redirect(request.referrer)
        elif DO == 'publish':
            if post.feed.user_can_publish(user):
                post.published = True
                post.publisher = user
                post.publish_date = datetime.now()
                post.save()
                flash ('Published')
            else:
                flash ('Sorry, You do NOT have publish' \
                       ' permissions on this feed.')
            return redirect(request.referrer)
        elif DO == 'unpublish':
            if post.feed.user_can_publish(user):
                post.published = False
                post.publisher = None
                post.publish_date = None
                post.save()
                flash ('Unpublished!')
            else:
                flash ('Sorry, you do NOT have permission' \
                       ' to unpublish on this feed.')
            return redirect(request.referrer)

        # finally get around to editing the content of the post...
        try:
            post_form_intake(post, request.form, editor)

            post.save()
            flash('Updated.')
        except:
            flash('invalid content for this data type!')

    # Should we bother displaying 'Post' button, and editable controls
    # if the user can't write to this post anyway?

    can_write, can_publish = can_user_write_and_publish(user, post)

    return render_template('post_editor.html',
                            post = post,
                            post_type = post.type,
                            current_feed = post.feed.id,
                            feedlist = user.writeable_feeds(),
                            can_write = can_write,
                            form_content = editor.form(json.loads(
                                post.content)))

@app.route('/posts/edittype/<typeid>')
def postedit_type(typeid):
    ''' returns an editor page, of type typeid '''

    editor = post_types.load(typeid)

    return render_template('post_type_container.html',
                           post_type = typeid,
                           form_content = editor.form(request.form))


###############################################################

@app.route('/external_data_sources/NEW', defaults={'source_id': None},
                                         methods=['GET','POST'])
@app.route('/external_data_sources/<int:source_id>',
                                         methods=['GET', 'POST', 'DELETE'])
def external_data_source_edit(source_id):
    ''' Editing a external data source '''

    if not user_session.is_admin():
        flash('Only Admins can do this!')
        return redirect(url_for('feeds'))

    # first find the data type:

    if request.method == 'DELETE':
        ExternalSource.delete().where(ExternalSource.id==int(source_id)).execute()
        return 'deleted'

    if source_id == None:
        try:
            source = ExternalSource()
            source.type = request.args['type']
            source.name = "new " + source.type + " source"
            source.feed = Feed.get() # set initial feed
        except KeyError:
            return 'No type specified.'
    else:
        try:
            source = ExternalSource.get(id=source_id)
        except peewee.DoesNotExist:
            return 'Invalid id.', 404

    # Try and load the external source type ( and check it's valid):

    try:
        module = external_source_types.load(source.type)
    except ImportError:
        return 'Invalid External Source Type', 404

    # if it's a post, then update the data with 'receive':

    if request.method == 'POST':
        source.settings = json.dumps(module.receive(request))
        source.name = request.form.get('name', source.name)
        source.post_as_user = user_session.get_user()
        source.frequency = int(request.form.get('frequency', 60))
        source.publish = request.form.get('publish', False)
        source.lifetime_start = request.form.get('lifetime_start',
                                                 source.lifetime_start)
        source.lifetime_end = request.form.get('lifetime_end',
                                                 source.lifetime_end)
        source.post_template = request.form.get('post_template',
                                                source.post_template)
        try:                                         
            source.feed = Feed.get(Feed.id==int(request.form.get('feed', 100)))
            source.save()
            if source_id == None:
                # new source!
                return redirect(url_for('external_data_source_edit',
                                        source_id = source.id))
            else:
                flash('Updated.')
        except Feed.DoesNotExist:
            flash ("Can't save! Invalid Feed!{}".format(
                int(request.form.get('feed', '-11'))))

    return render_template("external_source.html", source=source,
            feeds=Feed.select(),
            form=module.form(json.loads(source.settings)))

@app.route('/external_data_sources/test')
def external_source_test():
    '''
        test an external source, and return some comforting HTML
        (for the editor)
    '''
    if not user_session.is_admin():
        flash('Only Admins can do this!')
        return redirect(url_for('feeds'))

    '''
    try:
        source = ExternalSource.get(id=source_id)
    except ExternalSource.DoesNotExist:
        return 'Invalid Source.', 404
    '''
    # load the type module:
    module = external_source_types.load(request.args.get('type', None))
    # and request the test html
    return module.test(request.args)

@app.route('/external_data_sources/<int:source_id>/run')
def external_source_run(source_id):
    ''' use the importer specified to see if there is any new data,
        and if there is, then import it. '''

    try:
        source = ExternalSource.get(id=source_id)
    except ExternalSource.DoesNotExist:
        return 'Invalid Source', 404

    now = datetime.now()
    if source.last_checked:
        next_check = source.last_checked + timedelta(minutes=source.frequency)

        if (next_check > now):
            return "Nothing to do. Last: {0}, Next: {1}, Now: {2} ".format(
                source.last_checked, next_check, now)

    module = external_source_types.load(source.type)

    settings_data = json.loads(source.settings)
    new_posts = module.get_new(settings_data)

    if new_posts:
        for fresh_data in new_posts:
            post = Post(type=fresh_data.get('type', 'html'), author=source.post_as_user)
            editor = post_types.load(fresh_data.get('type', 'html'))

            post.feed = source.feed
            post_form_intake(post, fresh_data, editor)
            post.active_start = source.current_lifetime_start()
            post.active_end = source.current_lifetime_end()
            if source.publish:
                post.publisher = source.post_as_user
                post.publish_date = datetime.now()
                post.published = True
            post.save()
    # else, no new posts! oh well!

    source.settings = json.dumps(settings_data)
    source.last_checked = datetime.now()
    source.save()

    return 'Done!'


# NOTE! This address is HARD CODED into some of the screen and back end .js
# files.  If you change here, change there! (This isn't ideal, of course)

@app.route('/external_data_sources/')
def external_data_sources_update_all():
    ''' update all external data sources. '''
    sources = [x[0] for x in ExternalSource.select(ExternalSource.id).tuples()]
    print sources
    return json.dumps([(external_source_run(s), s) for s in sources])
