from unittest import TestCase
from otam.allocation import allocate
from otam.common import SafetyError


class CompleteTarAllocation(TestCase):
    def check_fit(self, sizes, capacities):
        result=allocate(sizes,capacities)
        self.assertEqual(len(result),len(sizes))
        for medium,capacity in enumerate(capacities):
            self.assertLessEqual(sum(s for s,m in zip(sizes,result) if m==medium),capacity)
        self.assertEqual(result,allocate(sizes,capacities))
        return result

    def test_reorders_whole_tars_to_avoid_unnecessary_third_medium(self):
        self.assertEqual(self.check_fit([4,4,6,6],[10,10]),[0,1,0,1])

    def test_native_boundary_and_oversized_tar(self):
        self.check_fit([100],[100])
        for sizes,caps in (([101],[100]),([6,6],[10]),([11],[10,10])):
            with self.assertRaises(SafetyError):allocate(sizes,caps)

    def test_lp_archive_real_metadata_estimates_on_two_native_lto4(self):
        sizes=[74090428780,74189378806,74696951620,74982316284,73654423390,
               74230186268,74911574140,72096347238,74838814334,61532902028,
               388772424710,73760712416,73898786354,68670816648,74075194790,
               74263654234,40068823350]
        self.check_fit(sizes,[800000000000-10240]*2)
        with self.assertRaises(SafetyError):allocate(sizes,[760000000000-10240]*2)
