import re
import inspect
from errno import EFAULT
from fuse import Operations, FUSE, FuseOSError

from gitfs.utils import Repository
from log import log


class Router(object):
    def __init__(self, remote_url, repos_path, mount_path, branch=None):
        """
        Clone repo from a remote into repos_path/<repo_name> and checkout to
        a specific branch.

        :param str remote_url: URL of the repository to clone
        :param str repos_path: Where are all the repos are cloned
        :param str branch: Branch to checkout after the
            clone. The default is to use the remote's default branch.

        """
        self.remote_url = remote_url
        self.repos_path = repos_path
        self.mount_path = mount_path
        self.branch = branch
        self.repo_path = self._get_repo(repos_path)

        self.operations = Operations()
        self.routes = []
        fuse_ops = set([elem[0]
                        for elem
                        in inspect.getmembers(FUSE, predicate=inspect.ismethod)])
        operations_ops = set([elem[0]
                              for elem in
                              inspect.getmembers(Operations,
                                                 predicate=inspect.ismethod)])
        self.fuse_class_ops = fuse_ops - operations_ops

        log.info('Cloning into %s' % self.repo_path)
        self.repo = Repository.clone(self.remote_url, self.repo_path,
                                     self.branch)
        log.info('Done INIT')

    def init(self, path):
        # XXX: Move back to __init__?
        #log.info('Cloning into %s' % self.repo_path)
        #self.repo = Repository.clone(self.remote_url, self.repo_path,
                                     #self.branch)
        log.info('Done INIT')

    def destroy(self, path):
        log.info('DESTROY')


    def __call__(self, op, *args):
        # TODO: check args for special methods
        if op in ['destroy', 'init']:
            view = self
        else:
            path = args[0]
            view, relative_path = self.get_view(path)
            relative_path = '/' if not relative_path else relative_path
            args = (relative_path,) + args[1:]
            log.info('args: %r', args)
        log.info('calling %s from %s with %r' % (op, view, args))
        if not hasattr(view, op):
            raise FuseOSError(EFAULT)
        return getattr(view, op)(*args)

    def register(self, regex, view):
        self.routes.append({
            'regex': regex,
            'view': view
        })

    def get_view(self, path):
        """
        Try to map a given path to it's specific view.

        If a match is found, a view object is created with the right regex
        groups(named or unnamed).

        :param str path: path to be matched
        :rtype: view object, relative path
        """

        for route in self.routes:
            result = re.search(route['regex'], path)
            if result is None:
                continue

            groups = result.groups()
            relative_path = re.sub(route['regex'], '', path)

            kwargs = result.groupdict()
            kwargs['repo_path'] = self.mount_path
            args = set(groups) - set(kwargs.values())

            return route['view'](*args, **kwargs), relative_path

        raise ValueError("View not found!")

    def __getattr__(self, attr_name):
        log.info('Getting %s attribute.' % attr_name)
        """
        Magic method which calls a specific method from a view.

        In Fuse API, almost each method receives a path argument. Based on that
        path we can route each call to a specific view. For example, if a
        method which has a path argument like `/current/dir1/dir2/file1` is
        called, we need to get the certain view that will know how to handle
        this path, instantiate it and then call our method on the newly created
        object.

        :param str attr_name: Method name to be called
        :rtype: function
        """

        if attr_name in self.fuse_class_ops:
            return None

        if attr_name not in dir(self.operations):
            message = 'Method %s is not implemented by this FS' % attr_name
            raise NotImplementedError(message)

        attr = getattr(self.operations, attr_name)
        if not callable(attr):
            raise ValueError('Invalid method')

        args = inspect.getargspec(attr).args
        if 'path' not in args:
            pass
            # TODO: route to special methods
            # - symlink
            # - rename
            # - link
            # - init
            # - destroy
            #raise Exception('route to special methods')

        def placeholder(path, *arg, **kwargs):
            view, relative_path = self.get_view(path)
            method = getattr(view, attr_name)
            return method(relative_path, *arg, **kwargs)

        return placeholder

    def _get_repo(self, repos_path):
        match = re.search(r"(?P<repo_name>[\w\-\_]+)\.git", self.remote_url)
        return "%s/%s" % (repos_path, match.group("repo_name"))