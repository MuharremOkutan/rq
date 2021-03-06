# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from rq import Queue
from rq.exceptions import InvalidJobDependency, NoSuchJobError
from rq.job import Job, JobStatus
from rq.registry import DeferredJobRegistry
from rq.worker import Worker
from tests import RQTestCase
from tests.fixtures import echo, say_hello


class CustomJob(Job):
    pass


class TestQueue(RQTestCase):
    def test_create_queue(self):
        """Creating queues."""
        q = Queue('my-queue')
        self.assertEqual(q.name, 'my-queue')
        self.assertEqual(str(q), '<Queue my-queue>')

    def test_create_default_queue(self):
        """Instantiating the default queue."""
        q = Queue()
        self.assertEqual(q.name, 'default')

    def test_equality(self):
        """Mathematical equality of queues."""
        q1 = Queue('foo')
        q2 = Queue('foo')
        q3 = Queue('bar')

        self.assertEqual(q1, q2)
        self.assertEqual(q2, q1)
        self.assertNotEqual(q1, q3)
        self.assertNotEqual(q2, q3)
        self.assertGreater(q1, q3)
        self.assertRaises(TypeError, lambda: q1 == 'some string')
        self.assertRaises(TypeError, lambda: q1 < 'some string')

    def test_empty_queue(self):
        """Emptying queues."""
        q = Queue('example')

        self.testconn.rpush('rq:queue:example', 'foo')
        self.testconn.rpush('rq:queue:example', 'bar')
        self.assertEqual(q.is_empty(), False)

        q.empty()

        self.assertEqual(q.is_empty(), True)
        self.assertIsNone(self.testconn.lpop('rq:queue:example'))

    def test_empty_removes_jobs(self):
        """Emptying a queue deletes the associated job objects"""
        q = Queue('example')
        job = q.enqueue(say_hello)
        self.assertTrue(Job.exists(job.id))
        q.empty()
        self.assertFalse(Job.exists(job.id))

    def test_queue_is_empty(self):
        """Detecting empty queues."""
        q = Queue('example')
        self.assertEqual(q.is_empty(), True)

        self.testconn.rpush('rq:queue:example', 'sentinel message')
        self.assertEqual(q.is_empty(), False)

    def test_queue_delete(self):
        """Test queue.delete properly removes queue"""
        q = Queue('example')
        job = q.enqueue(say_hello)
        job2 = q.enqueue(say_hello)

        self.assertEqual(2, len(q.get_job_ids()))

        q.delete()

        self.assertEqual(0, len(q.get_job_ids()))
        self.assertEqual(False, self.testconn.exists(job.key))
        self.assertEqual(False, self.testconn.exists(job2.key))
        self.assertEqual(0, len(self.testconn.smembers(Queue.redis_queues_keys)))
        self.assertEqual(False, self.testconn.exists(q.key))

    def test_queue_delete_but_keep_jobs(self):
        """Test queue.delete properly removes queue but keeps the job keys in the redis store"""
        q = Queue('example')
        job = q.enqueue(say_hello)
        job2 = q.enqueue(say_hello)

        self.assertEqual(2, len(q.get_job_ids()))

        q.delete(delete_jobs=False)

        self.assertEqual(0, len(q.get_job_ids()))
        self.assertEqual(True, self.testconn.exists(job.key))
        self.assertEqual(True, self.testconn.exists(job2.key))
        self.assertEqual(0, len(self.testconn.smembers(Queue.redis_queues_keys)))
        self.assertEqual(False, self.testconn.exists(q.key))

    def test_remove(self):
        """Ensure queue.remove properly removes Job from queue."""
        q = Queue('example')
        job = q.enqueue(say_hello)
        self.assertIn(job.id, q.job_ids)
        q.remove(job)
        self.assertNotIn(job.id, q.job_ids)

        job = q.enqueue(say_hello)
        self.assertIn(job.id, q.job_ids)
        q.remove(job.id)
        self.assertNotIn(job.id, q.job_ids)

    def test_jobs(self):
        """Getting jobs out of a queue."""
        q = Queue('example')
        self.assertEqual(q.jobs, [])
        job = q.enqueue(say_hello)
        self.assertEqual(q.jobs, [job])

        # Deleting job removes it from queue
        job.delete()
        self.assertEqual(q.job_ids, [])

    def test_compact(self):
        """Queue.compact() removes non-existing jobs."""
        q = Queue()

        q.enqueue(say_hello, 'Alice')
        q.enqueue(say_hello, 'Charlie')
        self.testconn.lpush(q.key, '1', '2')

        self.assertEqual(q.count, 4)
        self.assertEqual(len(q), 4)

        q.compact()

        self.assertEqual(q.count, 2)
        self.assertEqual(len(q), 2)

    def test_enqueue(self):
        """Enqueueing job onto queues."""
        q = Queue()
        self.assertEqual(q.is_empty(), True)

        # say_hello spec holds which queue this is sent to
        job = q.enqueue(say_hello, 'Nick', foo='bar')
        job_id = job.id
        self.assertEqual(job.origin, q.name)

        # Inspect data inside Redis
        q_key = 'rq:queue:default'
        self.assertEqual(self.testconn.llen(q_key), 1)
        self.assertEqual(
            self.testconn.lrange(q_key, 0, -1)[0].decode('ascii'),
            job_id)

    def test_enqueue_sets_metadata(self):
        """Enqueueing job onto queues modifies meta data."""
        q = Queue()
        job = Job.create(func=say_hello, args=('Nick',), kwargs=dict(foo='bar'))

        # Preconditions
        self.assertIsNone(job.enqueued_at)

        # Action
        q.enqueue_job(job)

        # Postconditions
        self.assertIsNotNone(job.enqueued_at)

    def test_pop_job_id(self):
        """Popping job IDs from queues."""
        # Set up
        q = Queue()
        uuid = '112188ae-4e9d-4a5b-a5b3-f26f2cb054da'
        q.push_job_id(uuid)

        # Pop it off the queue...
        self.assertEqual(q.count, 1)
        self.assertEqual(q.pop_job_id(), uuid)

        # ...and assert the queue count when down
        self.assertEqual(q.count, 0)

    def test_dequeue_any(self):
        """Fetching work from any given queue."""
        fooq = Queue('foo')
        barq = Queue('bar')

        self.assertEqual(Queue.dequeue_any([fooq, barq], None), None)

        # Enqueue a single item
        barq.enqueue(say_hello)
        job, queue = Queue.dequeue_any([fooq, barq], None)
        self.assertEqual(job.func, say_hello)
        self.assertEqual(queue, barq)

        # Enqueue items on both queues
        barq.enqueue(say_hello, 'for Bar')
        fooq.enqueue(say_hello, 'for Foo')

        job, queue = Queue.dequeue_any([fooq, barq], None)
        self.assertEqual(queue, fooq)
        self.assertEqual(job.func, say_hello)
        self.assertEqual(job.origin, fooq.name)
        self.assertEqual(
            job.args[0], 'for Foo',
            'Foo should be dequeued first.'
        )

        job, queue = Queue.dequeue_any([fooq, barq], None)
        self.assertEqual(queue, barq)
        self.assertEqual(job.func, say_hello)
        self.assertEqual(job.origin, barq.name)
        self.assertEqual(
            job.args[0], 'for Bar',
            'Bar should be dequeued second.'
        )

    def test_dequeue_any_ignores_nonexisting_jobs(self):
        """Dequeuing (from any queue) silently ignores non-existing jobs."""

        q = Queue('low')
        uuid = '49f205ab-8ea3-47dd-a1b5-bfa186870fc8'
        q.push_job_id(uuid)

        # Dequeue simply ignores the missing job and returns None
        self.assertEqual(q.count, 1)
        self.assertEqual(
            Queue.dequeue_any([Queue(), Queue('low')], None),  # noqa
            None
        )
        self.assertEqual(q.count, 0)
    
    def test_enqueue_with_ttl(self):
        """Negative TTL value is not allowed"""
        queue = Queue()
        self.assertRaises(ValueError, queue.enqueue, echo, 1, ttl=0)
        self.assertRaises(ValueError, queue.enqueue, echo, 1, ttl=-1)

    def test_enqueue_sets_status(self):
        """Enqueueing a job sets its status to "queued"."""
        q = Queue()
        job = q.enqueue(say_hello)
        self.assertEqual(job.get_status(), JobStatus.QUEUED)

    def test_enqueue_meta_arg(self):
        """enqueue() can set the job.meta contents."""
        q = Queue()
        job = q.enqueue(say_hello, meta={'foo': 'bar', 'baz': 42})
        self.assertEqual(job.meta['foo'], 'bar')
        self.assertEqual(job.meta['baz'], 42)

    def test_enqueue_with_failure_ttl(self):
        """enqueue() properly sets job.failure_ttl"""
        q = Queue()
        job = q.enqueue(say_hello, failure_ttl=10)
        job.refresh()
        self.assertEqual(job.failure_ttl, 10)

    def test_job_timeout(self):
        """Timeout can be passed via job_timeout argument"""
        queue = Queue()
        job = queue.enqueue(echo, 1, job_timeout=15)
        self.assertEqual(job.timeout, 15)

        # Not passing job_timeout will use queue._default_timeout
        job = queue.enqueue(echo, 1)
        self.assertEqual(job.timeout, queue._default_timeout)

        # job_timeout = 0 is not allowed
        self.assertRaises(ValueError, queue.enqueue, echo, 1, job_timeout=0)

    def test_default_timeout(self):
        """Timeout can be passed via job_timeout argument"""
        queue = Queue()
        job = queue.enqueue(echo, 1)
        self.assertEqual(job.timeout, queue.DEFAULT_TIMEOUT)

        job = Job.create(func=echo)
        job = queue.enqueue_job(job)
        self.assertEqual(job.timeout, queue.DEFAULT_TIMEOUT)

        queue = Queue(default_timeout=15)
        job = queue.enqueue(echo, 1)
        self.assertEqual(job.timeout, 15)

        job = Job.create(func=echo)
        job = queue.enqueue_job(job)
        self.assertEqual(job.timeout, 15)

    def test_enqueue_explicit_args(self):
        """enqueue() works for both implicit/explicit args."""
        q = Queue()

        # Implicit args/kwargs mode
        job = q.enqueue(echo, 1, job_timeout=1, result_ttl=1, bar='baz')
        self.assertEqual(job.timeout, 1)
        self.assertEqual(job.result_ttl, 1)
        self.assertEqual(
            job.perform(),
            ((1,), {'bar': 'baz'})
        )

        # Explicit kwargs mode
        kwargs = {
            'timeout': 1,
            'result_ttl': 1,
        }
        job = q.enqueue(echo, job_timeout=2, result_ttl=2, args=[1], kwargs=kwargs)
        self.assertEqual(job.timeout, 2)
        self.assertEqual(job.result_ttl, 2)
        self.assertEqual(
            job.perform(),
            ((1,), {'timeout': 1, 'result_ttl': 1})
        )

    def test_all_queues(self):
        """All queues"""
        q1 = Queue('first-queue')
        q2 = Queue('second-queue')
        q3 = Queue('third-queue')

        # Ensure a queue is added only once a job is enqueued
        self.assertEqual(len(Queue.all()), 0)
        q1.enqueue(say_hello)
        self.assertEqual(len(Queue.all()), 1)

        # Ensure this holds true for multiple queues
        q2.enqueue(say_hello)
        q3.enqueue(say_hello)
        names = [q.name for q in Queue.all()]
        self.assertEqual(len(Queue.all()), 3)

        # Verify names
        self.assertTrue('first-queue' in names)
        self.assertTrue('second-queue' in names)
        self.assertTrue('third-queue' in names)

        # Now empty two queues
        w = Worker([q2, q3])
        w.work(burst=True)

        # Queue.all() should still report the empty queues
        self.assertEqual(len(Queue.all()), 3)

    def test_all_custom_job(self):
        class CustomJob(Job):
            pass

        q = Queue('all-queue')
        q.enqueue(say_hello)
        queues = Queue.all(job_class=CustomJob)
        self.assertEqual(len(queues), 1)
        self.assertIs(queues[0].job_class, CustomJob)

    def test_from_queue_key(self):
        """Ensure being able to get a Queue instance manually from Redis"""
        q = Queue()
        key = Queue.redis_queue_namespace_prefix + 'default'
        reverse_q = Queue.from_queue_key(key)
        self.assertEqual(q, reverse_q)

    def test_from_queue_key_error(self):
        """Ensure that an exception is raised if the queue prefix is wrong"""
        key = 'some:weird:prefix:' + 'default'
        self.assertRaises(ValueError, Queue.from_queue_key, key)

    def test_enqueue_dependents(self):
        """Enqueueing dependent jobs pushes all jobs in the depends set to the queue
        and removes them from DeferredJobQueue."""
        q = Queue()
        parent_job = Job.create(func=say_hello)
        parent_job.save()
        job_1 = q.enqueue(say_hello, depends_on=parent_job)
        job_2 = q.enqueue(say_hello, depends_on=parent_job)

        registry = DeferredJobRegistry(q.name, connection=self.testconn)
        self.assertEqual(
            set(registry.get_job_ids()),
            set([job_1.id, job_2.id])
        )
        # After dependents is enqueued, job_1 and job_2 should be in queue
        self.assertEqual(q.job_ids, [])
        q.enqueue_dependents(parent_job)
        self.assertEqual(set(q.job_ids), set([job_2.id, job_1.id]))
        self.assertFalse(self.testconn.exists(parent_job.dependents_key))

        # DeferredJobRegistry should also be empty
        self.assertEqual(registry.get_job_ids(), [])

    def test_enqueue_dependents_on_multiple_queues(self):
        """Enqueueing dependent jobs on multiple queues pushes jobs in the queues
        and removes them from DeferredJobRegistry for each different queue."""
        q_1 = Queue("queue_1")
        q_2 = Queue("queue_2")
        parent_job = Job.create(func=say_hello)
        parent_job.save()
        job_1 = q_1.enqueue(say_hello, depends_on=parent_job)
        job_2 = q_2.enqueue(say_hello, depends_on=parent_job)

        # Each queue has its own DeferredJobRegistry
        registry_1 = DeferredJobRegistry(q_1.name, connection=self.testconn)
        self.assertEqual(
            set(registry_1.get_job_ids()),
            set([job_1.id])
        )
        registry_2 = DeferredJobRegistry(q_2.name, connection=self.testconn)
        self.assertEqual(
            set(registry_2.get_job_ids()),
            set([job_2.id])
        )

        # After dependents is enqueued, job_1 on queue_1 and
        # job_2 should be in queue_2
        self.assertEqual(q_1.job_ids, [])
        self.assertEqual(q_2.job_ids, [])
        q_1.enqueue_dependents(parent_job)
        q_2.enqueue_dependents(parent_job)
        self.assertEqual(set(q_1.job_ids), set([job_1.id]))
        self.assertEqual(set(q_2.job_ids), set([job_2.id]))
        self.assertFalse(self.testconn.exists(parent_job.dependents_key))

        # DeferredJobRegistry should also be empty
        self.assertEqual(registry_1.get_job_ids(), [])
        self.assertEqual(registry_2.get_job_ids(), [])

    def test_enqueue_job_with_dependency(self):
        """Jobs are enqueued only when their dependencies are finished."""
        # Job with unfinished dependency is not immediately enqueued
        parent_job = Job.create(func=say_hello)
        parent_job.save()
        q = Queue()
        job = q.enqueue_call(say_hello, depends_on=parent_job)
        self.assertEqual(q.job_ids, [])
        self.assertEqual(job.get_status(), JobStatus.DEFERRED)

        # Jobs dependent on finished jobs are immediately enqueued
        parent_job.set_status(JobStatus.FINISHED)
        parent_job.save()
        job = q.enqueue_call(say_hello, depends_on=parent_job)
        self.assertEqual(q.job_ids, [job.id])
        self.assertEqual(job.timeout, Queue.DEFAULT_TIMEOUT)
        self.assertEqual(job.get_status(), JobStatus.QUEUED)

    def test_enqueue_job_with_dependency_by_id(self):
        """Can specify job dependency with job object or job id."""
        parent_job = Job.create(func=say_hello)
        parent_job.save()

        q = Queue()
        q.enqueue_call(say_hello, depends_on=parent_job.id)
        self.assertEqual(q.job_ids, [])

        # Jobs dependent on finished jobs are immediately enqueued
        parent_job.set_status(JobStatus.FINISHED)
        parent_job.save()
        job = q.enqueue_call(say_hello, depends_on=parent_job.id)
        self.assertEqual(q.job_ids, [job.id])
        self.assertEqual(job.timeout, Queue.DEFAULT_TIMEOUT)

    def test_enqueue_job_with_dependency_and_timeout(self):
        """Jobs remember their timeout when enqueued as a dependency."""
        # Job with unfinished dependency is not immediately enqueued
        parent_job = Job.create(func=say_hello)
        parent_job.save()
        q = Queue()
        job = q.enqueue_call(say_hello, depends_on=parent_job, timeout=123)
        self.assertEqual(q.job_ids, [])
        self.assertEqual(job.timeout, 123)

        # Jobs dependent on finished jobs are immediately enqueued
        parent_job.set_status(JobStatus.FINISHED)
        parent_job.save()
        job = q.enqueue_call(say_hello, depends_on=parent_job, timeout=123)
        self.assertEqual(q.job_ids, [job.id])
        self.assertEqual(job.timeout, 123)

    def test_enqueue_job_with_invalid_dependency(self):
        """Enqueuing a job fails, if the dependency does not exist at all."""
        parent_job = Job.create(func=say_hello)
        # without save() the job is not visible to others

        q = Queue()
        with self.assertRaises(NoSuchJobError):
            q.enqueue_call(say_hello, depends_on=parent_job)

        with self.assertRaises(NoSuchJobError):
            q.enqueue_call(say_hello, depends_on=parent_job.id)

        self.assertEqual(q.job_ids, [])

    def test_fetch_job_successful(self):
        """Fetch a job from a queue."""
        q = Queue('example')
        job_orig = q.enqueue(say_hello)
        job_fetch = q.fetch_job(job_orig.id)
        self.assertIsNotNone(job_fetch)
        self.assertEqual(job_orig.id, job_fetch.id)
        self.assertEqual(job_orig.description, job_fetch.description)

    def test_fetch_job_missing(self):
        """Fetch a job from a queue which doesn't exist."""
        q = Queue('example')
        job = q.fetch_job('123')
        self.assertIsNone(job)

    def test_fetch_job_different_queue(self):
        """Fetch a job from a queue which is in a different queue."""
        q1 = Queue('example1')
        q2 = Queue('example2')
        job_orig = q1.enqueue(say_hello)
        job_fetch = q2.fetch_job(job_orig.id)
        self.assertIsNone(job_fetch)

        job_fetch = q1.fetch_job(job_orig.id)
        self.assertIsNotNone(job_fetch)
